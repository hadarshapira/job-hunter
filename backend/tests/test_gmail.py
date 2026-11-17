"""Gmail tracking: email rules, matching to jobs, and the full check with a fake Gmail (no network)."""

import base64
import json
from datetime import datetime, timedelta, timezone
from urllib.parse import parse_qs, urlparse

import httpx
import pytest
from sqlalchemy import select

from app import api_gmail
from app.config import get_settings
from app.models import GmailAccount, GmailMessage, Job
from app.services.gmail import oauth
from app.services.gmail.classify import CONFIRMATION, INTERVIEW, REJECTION, classify
from app.services.gmail.client import Mail
from app.services.gmail.match import guess
from tests.conftest import new_client, signup


@pytest.fixture(autouse=True)
def gmail_secret(monkeypatch):
    monkeypatch.setenv("GOOGLE_CLIENT_SECRET", "test-secret-value")
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


# ---------- rules ----------

@pytest.mark.parametrize("subject,text,kind", [
    ("Thank you for applying to Wix", "We received your application for the Senior Data Engineer position.", CONFIRMATION),
    ("Alex, your application was sent to Acme", "Your application was sent to Acme\nData Engineer", CONFIRMATION),
    ("Application received", "Thanks for applying! If your experience fits, we will contact you to schedule an interview.", CONFIRMATION),
    ("Thank you for your application", "Due to the high volume of applications, unfortunately we can't respond to every applicant individually.", CONFIRMATION),
    ("קיבלנו את מועמדותך", "שלום, קיבלנו את קורות החיים שלך למשרת מהנדס/ת דאטה. ניצור קשר אם יהיה מתאים.", CONFIRMATION),
    ("המועמדות שלך התקבלה במערכת", "היי, תודה על הזמן שהקדשת להגשת מועמדות למשרה. קורות החיים שלך עברו לצוות הגיוס "
     "ובמידה שתהיה התאמה ניצור איתך קשר.", CONFIRMATION),
    ("Your application to Aidoc", "Thank you for your interest. Unfortunately, we have decided to move forward with other candidates.", REJECTION),
    ("Update on your application", "After careful consideration we will not be moving forward with your application for the role.", REJECTION),
    ("Update regarding your application at Northwind",
     "Dear Alex\n\nThanks for applying to the Senior Data Engineer role at Northwind.\n\n"
     "We have decided to move forward with candidates whose experience and background "
     "better match the role.\nThank you again.", REJECTION),
    ("Your application", "Thanks for applying. We won't be moving forward with your application at this time.", REJECTION),
    ("Your application", "Thanks for applying. We have decided to go in a different direction for this role.", REJECTION),
    ("Thank you from Contoso",
     "Hi Alex,\n\nThanks for your interest in Contoso.\n\n"
     "After reviewing your CV, we made the decision not to move forward in the process this time.\n\n"
     "We wish you the best of luck.", REJECTION),
    ("Your application", "Thanks for applying. We decided to proceed with a different candidate for this role.", REJECTION),
    ("עדכון לגבי מועמדותך", "תודה על התעניינותך במשרה. לצערנו החלטנו להתקדם עם מועמדים אחרים.", REJECTION),
    ("Interview - Data Engineer at Claroty", "We'd love to invite you to an interview. Please pick a time: https://calendly.com/x", INTERVIEW),
    ("Next steps", "Thanks for applying to the Data Platform role. We would like to schedule a phone screen with you this week.", INTERVIEW),
    ("ראיון עבודה", "היי, נשמח לזמן אותך לראיון לתפקיד Data Engineer. מתי נוח לך?", INTERVIEW),
    ("New jobs for you", "Data Engineer at Wix and 10 more jobs you may be interested in. Apply now.", None),
    ("Your weekly digest", "Here's what happened on GitHub this week.", None),
    ("Your application was viewed by Wix", "Your application was viewed by Wix for Data Engineer.", None),
])
def test_classify(subject, text, kind):
    assert classify(subject, text) == kind


def test_job_alert_senders_ignored():
    assert classify("Data Engineer jobs", "Thank you for applying", "LinkedIn <jobalerts-noreply@linkedin.com>") is None


def _mail(subject: str, text: str, name: str = "", addr: str = "no-reply@greenhouse.io") -> Mail:
    return Mail(id="m", thread_id="t", sender_name=name, sender_email=addr, subject=subject, text=text,
                received_at=datetime.now(timezone.utc), labels=["INBOX"])


@pytest.mark.parametrize("mail,company,title", [
    (_mail("Alex, your application was sent to Globex", "Your application was sent to Globex", addr="jobs-noreply@linkedin.com"),
     "Globex", ""),
    (_mail("Thanks for applying", "Thank you for applying for the Senior Data Engineer position at Riskified.", "Riskified Careers"),
     "Riskified", "Senior Data Engineer"),
    (_mail("Application received", "We got your application.", "Dana Levi", "dana@payoneer.com"), "Payoneer", ""),
    (_mail("Application received", "We got your application.", "Taboola Recruiting"), "Taboola", ""),
])
def test_guess_company_and_title(mail, company, title):
    g = guess(mail)
    assert g.company == company and g.title == title


# ---------- fake Google ----------

def _part(text: str, mime: str = "text/plain") -> dict:
    return {"mimeType": mime, "body": {"data": base64.urlsafe_b64encode(text.encode()).decode()}}


class FakeGoogle:
    def __init__(self):
        self.inbox: dict[str, dict] = {}
        self.labels = [{"id": "INBOX", "name": "INBOX"}]
        self.modified: list[tuple[str, list, list]] = []
        self.revoked = False
        self.refresh_ok = True

    def add(self, mid, subject, text, sender="Wix Careers <no-reply@greenhouse.io>", minutes_ago=0, thread=None):
        when = datetime.now(timezone.utc) - timedelta(minutes=minutes_ago)
        self.inbox[mid] = {
            "id": mid, "threadId": thread or f"t{mid}", "labelIds": ["INBOX"], "internalDate": str(int(when.timestamp() * 1000)),
            "payload": {"mimeType": "multipart/alternative",
                        "headers": [{"name": "From", "value": sender}, {"name": "Subject", "value": subject}],
                        "parts": [_part(text), _part(f"<p>{text}</p>", "text/html")]},
        }

    def handler(self, req: httpx.Request) -> httpx.Response:
        url, path = str(req.url), req.url.path
        if url.startswith(oauth.TOKEN_URL):
            form = parse_qs(req.content.decode())
            if form["grant_type"] == ["authorization_code"]:
                return httpx.Response(200, json={"access_token": "at", "refresh_token": "rt-123", "scope": oauth.SCOPE})
            return httpx.Response(200, json={"access_token": "at"}) if self.refresh_ok else httpx.Response(400, json={"error": "invalid_grant"})
        if url.startswith(oauth.REVOKE_URL):
            self.revoked = True
            return httpx.Response(200)
        assert req.headers["Authorization"] == "Bearer at"
        base = "/gmail/v1/users/me"
        if path == f"{base}/profile":
            return httpx.Response(200, json={"emailAddress": "me@gmail.com", "historyId": "1"})
        if path == f"{base}/messages":  # search: supports "in:inbox after:<unix seconds>"
            q = req.url.params["q"]
            after = int(q.split("after:")[1].split()[0]) if "after:" in q else 0
            hits = [m for m, d in self.inbox.items()
                    if "INBOX" in d["labelIds"] and int(d["internalDate"]) // 1000 >= after]
            return httpx.Response(200, json={"messages": [{"id": m} for m in hits]})
        if path.startswith(f"{base}/messages/") and path.endswith("/modify"):
            mid = path.split("/")[-2]
            body = json.loads(req.content)
            self.modified.append((mid, body["addLabelIds"], body["removeLabelIds"]))
            labels = self.inbox[mid]["labelIds"]
            labels[:] = [x for x in labels if x not in body["removeLabelIds"]] + body["addLabelIds"]
            return httpx.Response(200, json={})
        if path.startswith(f"{base}/messages/"):
            return httpx.Response(200, json=self.inbox[path.rsplit("/", 1)[-1]])
        if path == f"{base}/labels" and req.method == "GET":
            return httpx.Response(200, json={"labels": self.labels})
        if path == f"{base}/labels":
            lb = {"id": f"Label_{len(self.labels)}", "name": json.loads(req.content)["name"]}
            self.labels.append(lb)
            return httpx.Response(200, json=lb)
        return httpx.Response(404)


@pytest.fixture
def google(monkeypatch):
    g = FakeGoogle()
    monkeypatch.setattr(api_gmail, "http_client", lambda: httpx.AsyncClient(transport=httpx.MockTransport(g.handler)))
    return g


async def connect(c, google) -> None:
    r = await c.get("/api/gmail/connect")
    assert r.status_code == 303
    q = parse_qs(urlparse(r.headers["location"]).query)
    assert q["scope"] == [oauth.SCOPE] and q["access_type"] == ["offline"]
    assert q["redirect_uri"] == ["https://test/api/gmail/callback"]  # from the request's host
    r = await c.get("/api/gmail/callback", params={"state": q["state"][0], "code": "abc"})
    assert r.status_code == 303 and "gmail=connected" in r.headers["location"]


async def add_job(c, title, company, status="saved") -> int:
    r = await c.post("/api/jobs", json={"title": title, "company": company, "location": "Tel Aviv", "status": status})
    assert r.status_code == 201
    return r.json()["id"]


async def job(c, jid) -> dict:
    return (await c.get(f"/api/jobs/{jid}")).json()


# ---------- end to end ----------

async def test_connect_stores_token_encrypted_and_reads_recent_mail(authed, maker, google):
    # A reply that came shortly before connecting counts; one older than the lookback window doesn't
    google.add("recent", "Your application to Wix", "Unfortunately, we decided to move forward with other candidates.",
               minutes_ago=60)
    google.add("ancient", "Thank you for applying to Wix", "We received your application for the Data Engineer role.",
               minutes_ago=60 * 24 * 30)
    jid = await add_job(authed, "Data Engineer", "Wix", status="interview")
    await connect(authed, google)
    async with maker() as s:
        acc = (await s.scalars(select(GmailAccount))).one()
    assert acc.email == "me@gmail.com" and "rt-123" not in acc.refresh_token
    assert oauth.decrypt(get_settings(), acc.refresh_token) == "rt-123"

    r = await authed.post("/api/gmail/sync")
    assert r.json()["checked"] == 1 and r.json()["updated"] == 1
    assert (await job(authed, jid))["status"] == "rejected"
    assert [m for m, *_ in google.modified] == ["recent"]

    r = await authed.post("/api/gmail/sync")  # second check follows new mail only
    assert r.json()["checked"] == 0
    status = (await authed.get("/api/gmail/status")).json()
    assert status["connected"] and status["email"] == "me@gmail.com" and status["last_error"] == ""


async def test_confirmation_rejection_interview(authed, google):
    wix = await add_job(authed, "Senior Data Engineer", "Wix")
    aidoc = await add_job(authed, "Data Engineer", "Aidoc", status="applied")
    claroty = await add_job(authed, "Data Platform Engineer", "Claroty", status="applied")
    await connect(authed, google)
    google.add("1", "Thank you for applying to Wix", "We received your application for the Senior Data Engineer position.")
    google.add("2", "Your application to Aidoc", "Unfortunately, we decided to move forward with other candidates.",
               sender="Aidoc Talent <talent@aidoc.com>")
    google.add("3", "Interview with Claroty", "We'd like to invite you to an interview for the Data Platform Engineer role.",
               sender="Noa from Claroty <noa@claroty.com>")
    google.add("4", "Lunch on Friday?", "Want to grab lunch?", sender="friend@gmail.com")

    r = (await authed.post("/api/gmail/sync")).json()
    assert r == {"checked": 4, "job_emails": 3, "updated": 3, "unmatched": 0, "error": ""}

    assert (await job(authed, wix))["status"] == "applied"
    assert (await job(authed, aidoc))["status"] == "rejected"
    j = await job(authed, claroty)
    assert j["status"] == "interview"
    assert any(e["kind"] == "email" and e["url"].endswith("#all/3") for e in j["events"])

    ids = {lb["name"]: lb["id"] for lb in google.labels}
    assert google.inbox["1"]["labelIds"] == [ids["Job search/Applied"]]
    assert google.inbox["2"]["labelIds"] == [ids["Job search/Rejected"]]
    assert "Job search" in ids  # the parent label exists, so Gmail shows the two nested under it
    assert google.inbox["3"]["labelIds"] == ["INBOX"]  # interview stays in the Inbox
    assert google.inbox["4"]["labelIds"] == ["INBOX"]
    assert len(google.labels) == 4  # INBOX + parent + two sub-labels, each made once

    # Nothing is done twice; the emails put back in the Inbox are not handled again
    google.inbox["1"]["labelIds"] = ["INBOX"]
    again = (await authed.post("/api/gmail/sync")).json()
    assert again["job_emails"] == 0 and len(google.modified) == 2


async def test_every_check_rereads_todays_inbox(authed, google, monkeypatch):
    # An email from earlier today that a check skipped (e.g. the rules didn't know its wording) is
    # looked at again by the next check
    from app.services.gmail import sync

    jid = await add_job(authed, "Data Warehouse Tech Lead", "Contoso", status="applied")
    await connect(authed, google)
    google.add("1", "Thank you from Contoso", "After reviewing your CV, we made the decision not to move forward.",
               sender="Team Contoso <jobs@contoso.example>", minutes_ago=90)
    real = sync.classify
    monkeypatch.setattr(sync, "classify", lambda *a: None)  # rules that miss it
    assert (await authed.post("/api/gmail/sync")).json()["job_emails"] == 0
    assert (await authed.post("/api/gmail/sync")).json()["job_emails"] == 0
    monkeypatch.setattr(sync, "classify", real)  # rules fixed
    r = (await authed.post("/api/gmail/sync")).json()
    assert r["job_emails"] == 1 and r["updated"] == 1
    assert (await job(authed, jid))["status"] == "rejected"


async def test_never_moves_backwards_but_still_files_email(authed, google):
    jid = await add_job(authed, "Data Engineer", "Wix", status="interview")
    await connect(authed, google)
    google.add("1", "Thank you for applying to Wix", "We received your application for the Data Engineer position.")
    await authed.post("/api/gmail/sync")
    assert (await job(authed, jid))["status"] == "interview"
    msgs = (await authed.get("/api/gmail/messages")).json()
    assert msgs[0]["action"] == "no_change" and msgs[0]["moved"]


async def test_unknown_job_is_added_as_applied(authed, google):
    await connect(authed, google)
    google.add("1", "Thanks for applying", "Thank you for applying for the Senior Data Engineer position at Riskified.",
               sender="Riskified Careers <no-reply@greenhouse.io>")
    await authed.post("/api/gmail/sync")
    jobs = (await authed.get("/api/jobs")).json()
    assert [(j["company"], j["title"], j["status"], j["source"]) for j in jobs] == [
        ("Riskified", "Senior Data Engineer", "applied", "email")]
    msg = (await authed.get("/api/gmail/messages")).json()[0]
    assert msg["action"] == "created_job" and msg["moved"]

    # Undo removes the job and puts the email back in the Inbox
    r = await authed.post(f"/api/gmail/messages/{msg['id']}/undo")
    assert r.status_code == 200 and r.json()["action"] == "undone"
    assert (await authed.get("/api/jobs")).json() == []
    assert "INBOX" in google.inbox["1"]["labelIds"]


async def test_unclear_rejection_waits_for_user(authed, google):
    a = await add_job(authed, "Data Engineer", "Wix", status="applied")
    b = await add_job(authed, "Analytics Engineer", "Wix", status="applied")
    await connect(authed, google)
    google.add("1", "Your application", "Unfortunately, we will not be moving forward with your application.")
    r = (await authed.post("/api/gmail/sync")).json()
    assert r["unmatched"] == 1
    assert google.modified == []  # not moved until you pick the job
    msg = (await authed.get("/api/gmail/messages")).json()[0]
    assert msg["action"] == "unmatched" and msg["company_guess"] == "Wix"

    r = await authed.post(f"/api/gmail/messages/{msg['id']}/assign", json={"job_id": b})
    assert r.status_code == 200 and r.json()["job_id"] == b
    assert (await job(authed, b))["status"] == "rejected" and (await job(authed, a))["status"] == "applied"
    assert google.inbox["1"]["labelIds"] != ["INBOX"]

    r = await authed.post(f"/api/gmail/messages/{msg['id']}/undo")
    assert (await job(authed, b))["status"] == "applied" and "INBOX" in google.inbox["1"]["labelIds"]


async def test_revoked_access_shows_error(authed, google):
    await connect(authed, google)
    google.refresh_ok = False
    r = (await authed.post("/api/gmail/sync")).json()
    assert "Connect Gmail again" in r["error"]


async def test_callback_rejects_bad_state(client, maker, google):
    await signup(client, "a@example.com")
    r = await client.get("/api/gmail/callback", params={"state": "forged", "code": "abc"})
    assert "gmail=expired" in r.headers["location"]
    async with maker() as s:
        assert (await s.scalars(select(GmailAccount))).all() == []


async def test_disconnect_revokes(authed, maker, google):
    await connect(authed, google)
    assert (await authed.post("/api/gmail/disconnect")).status_code == 204
    assert google.revoked and not (await authed.get("/api/gmail/status")).json()["connected"]


async def test_reconnect_starts_fresh(authed, maker, google):
    jid = await add_job(authed, "Data Engineer", "Wix", status="interview")
    google.add("1", "Your application to Wix", "Unfortunately, we decided to move forward with other candidates.",
               minutes_ago=60)
    await connect(authed, google)
    assert (await authed.post("/api/gmail/sync")).json()["updated"] == 1
    await authed.post("/api/gmail/disconnect")
    async with maker() as s:
        assert (await s.scalars(select(GmailMessage))).all() == []
    # The user sets the job back and puts the email back in the Inbox, then connects again
    await authed.patch(f"/api/jobs/{jid}", json={"status": "interview"})
    google.inbox["1"]["labelIds"] = ["INBOX"]
    await connect(authed, google)
    assert (await authed.post("/api/gmail/sync")).json()["updated"] == 1
    assert (await job(authed, jid))["status"] == "rejected"


async def test_other_users_cannot_see_or_touch_your_emails(authed, maker, google):
    await add_job(authed, "Data Engineer", "Wix", status="applied")
    await connect(authed, google)
    google.add("1", "Your application", "Unfortunately, we will not be moving forward with your application.")
    google.add("2", "Your application", "Unfortunately, we decided not to proceed.", sender="Monday <jobs@monday.com>")
    await authed.post("/api/gmail/sync")
    mine = (await authed.get("/api/gmail/messages")).json()
    assert mine

    async with new_client() as other:
        await signup(other, "eve@example.com")
        assert (await other.get("/api/gmail/messages")).json() == []
        assert not (await other.get("/api/gmail/status")).json()["connected"]
        eve_job = await add_job(other, "Data Engineer", "Monday", status="applied")
        for m in mine:
            assert (await other.post(f"/api/gmail/messages/{m['id']}/undo")).status_code == 404
            r = await other.post(f"/api/gmail/messages/{m['id']}/assign", json={"job_id": eve_job})
            assert r.status_code == 404
        assert (await other.post("/api/gmail/sync")).status_code == 400

    # ...and your emails can't be linked to someone else's job
    unmatched = [m for m in mine if m["action"] == "unmatched"]
    assert unmatched
    r = await authed.post(f"/api/gmail/messages/{unmatched[0]['id']}/assign", json={"job_id": eve_job})
    assert r.status_code == 404
    async with maker() as s:
        assert all(m.user_id == 1 for m in (await s.scalars(select(GmailMessage))).all())
        assert (await s.get(Job, eve_job)).status == "applied"


async def test_custom_label_names(authed, google):
    """Each user picks their own label names; undo takes off the label and its parent."""
    st = (await authed.get("/api/gmail/status")).json()
    assert st["labels"] == {"confirmation": "Job search/Applied", "rejection": "Job search/Rejected"}
    bad = await authed.put("/api/gmail/labels", json={"confirmation": " / ", "rejection": "x"})
    assert bad.status_code == 422
    r = await authed.put("/api/gmail/labels", json={"confirmation": " Work / Applied ", "rejection": "Work/No"})
    assert r.json() == {"confirmation": "Work/Applied", "rejection": "Work/No"}
    assert (await authed.get("/api/gmail/status")).json()["labels"]["rejection"] == "Work/No"

    wix = await add_job(authed, "Senior Data Engineer", "Wix")
    await connect(authed, google)
    google.add("1", "Thank you for applying to Wix", "We received your application for the Senior Data Engineer position.")
    await authed.post("/api/gmail/sync")
    ids = {lb["name"]: lb["id"] for lb in google.labels}
    assert google.inbox["1"]["labelIds"] == [ids["Work/Applied"]] and "Work" in ids
    assert (await job(authed, wix))["status"] == "applied"

    google.inbox["1"]["labelIds"].append(ids["Work"])  # an older email filed under the parent
    msg = (await authed.get("/api/gmail/messages")).json()[0]
    await authed.post(f"/api/gmail/messages/{msg['id']}/undo")
    assert google.inbox["1"]["labelIds"] == ["INBOX"]


async def test_labels_are_per_user(authed, client):
    await authed.put("/api/gmail/labels", json={"confirmation": "Mine/Applied", "rejection": "Mine/Rejected"})
    await signup(client, "other@example.com")
    assert (await client.get("/api/gmail/status")).json()["labels"]["confirmation"] == "Job search/Applied"
