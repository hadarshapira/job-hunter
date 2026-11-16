"""Read new Inbox mail, update job statuses and file job emails under the user's label.

Runs every 10 minutes in the worker and from the "Check now" button. The first check after
connecting also looks back LOOKBACK days, so replies that came just before connecting count too. Only job emails are stored, and only their sender,
subject, date and what was done.
"""

import logging
from datetime import datetime, timedelta, timezone

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from sqlalchemy.orm import selectinload

from app.config import Settings, get_settings
from app.models import Event, GmailAccount, GmailMessage, Job, Status
from app.services import matching
from app.services.dedup import dedup_key
from app.services.gmail import oauth
from app.services.gmail.classify import CONFIRMATION, INTERVIEW, LABELS, REJECTION, classify
from app.services.gmail.client import Gmail, HistoryExpired, Mail
from app.services.gmail.match import best_job, guess, score

log = logging.getLogger("jobhunter.gmail")
LABEL_NAME = "Job search"
MOVE_KINDS = {CONFIRMATION, REJECTION}  # interview emails stay in the Inbox
LOOKBACK = timedelta(days=14)  # how far back the first check after connecting reads

# Never move a job backwards: which statuses each kind of email may change
_FROM = {
    CONFIRMATION: {Status.new, Status.saved},
    INTERVIEW: {Status.new, Status.saved, Status.applied, Status.screening},
    REJECTION: {s for s in Status if s not in (Status.offer, Status.rejected)},
}
_TO = {CONFIRMATION: Status.applied, INTERVIEW: Status.interview, REJECTION: Status.rejected}


def gmail_link(account: GmailAccount, gmail_id: str) -> str:
    return f"https://mail.google.com/mail/?authuser={account.email}#all/{gmail_id}"


async def open_gmail(client: httpx.AsyncClient, settings: Settings, account: GmailAccount) -> Gmail:
    token = await oauth.access_token(client, settings, oauth.decrypt(settings, account.refresh_token))
    return Gmail(client, token)


async def _label(gmail: Gmail, account: GmailAccount) -> str:
    if not account.label_id:
        account.label_id = await gmail.label_id(LABEL_NAME)
    return account.label_id


async def _move(gmail: Gmail, account: GmailAccount, msg: GmailMessage) -> None:
    label = await _label(gmail, account)
    try:
        await gmail.modify(msg.gmail_id, add=[label], remove=["INBOX"])
    except httpx.HTTPStatusError as e:
        if e.response.status_code != 400:
            raise
        account.label_id = None  # label was deleted in Gmail: make it again
        await gmail.modify(msg.gmail_id, add=[await _label(gmail, account)], remove=["INBOX"])
    msg.moved = True


def _aware(t: datetime) -> datetime:
    return t if t.tzinfo else t.replace(tzinfo=timezone.utc)


def _sender(mail: Mail) -> str:
    return f"{mail.sender_name} <{mail.sender_email}>" if mail.sender_name else mail.sender_email


async def act(session: AsyncSession, gmail: Gmail, account: GmailAccount, msg: GmailMessage, job: Job) -> None:
    """Apply the email to the job: timeline entry, status change if it moves forward, label."""
    msg.job_id = job.id
    msg.previous_status = job.status
    who = msg.sender.split("<")[0].strip() or msg.sender
    job.events.append(Event(kind="email", text=f"{LABELS[msg.kind]} email from {who}: “{msg.subject}”",
                            url=gmail_link(account, msg.gmail_id)))
    target = _TO[msg.kind]
    if job.status in _FROM[msg.kind]:
        from app.api import _apply_status  # shared with manual status changes

        _apply_status(job, target)
        msg.action = "status_changed" if msg.action != "created_job" else msg.action
    elif msg.action != "created_job":
        msg.action = "no_change"
    job.updated_at = datetime.now(timezone.utc)
    if msg.kind in MOVE_KINDS:
        await _move(gmail, account, msg)


async def _jobs(session: AsyncSession, user_id: int) -> list[Job]:
    return list((await session.scalars(
        select(Job).where(Job.user_id == user_id).options(selectinload(Job.events)))).all())


async def handle(session: AsyncSession, gmail: Gmail, account: GmailAccount, mail: Mail) -> GmailMessage | None:
    kind = classify(mail.subject, mail.text, _sender(mail))
    if kind is None:
        return None  # not a job email: nothing is stored
    jobs = await _jobs(session, account.user_id)
    thread_jobs = set((await session.scalars(select(GmailMessage.job_id).where(
        GmailMessage.user_id == account.user_id, GmailMessage.thread_id == mail.thread_id,
        GmailMessage.job_id.is_not(None)))).all()) if mail.thread_id else set()
    g = guess(mail)
    msg = GmailMessage(user_id=account.user_id, gmail_id=mail.id, thread_id=mail.thread_id, sender=_sender(mail)[:320],
                       subject=mail.subject[:500], received_at=mail.received_at, kind=kind, action="unmatched",
                       company_guess=g.company[:200], title_guess=g.title[:300])
    session.add(msg)
    job = best_job(mail, kind, jobs, thread_jobs)
    if job is None and kind == CONFIRMATION and g.company and not any(score(mail, j, thread_jobs) >= 3 for j in jobs):
        # Applied somewhere the app didn't know about: add the job
        title = g.title or "Position from email"
        job = Job(user_id=account.user_id, source="email", title=title[:300], company=g.company[:200], location="",
                  dedup_key=dedup_key(title, g.company, ""), status=Status.saved,
                  events=[Event(kind="created", text="Added from an email", url=gmail_link(account, mail.id))])
        session.add(job)
        await matching.apply_one(session, job)
        await session.flush()
        msg.action = "created_job"
    if job is not None:
        await act(session, gmail, account, msg, job)
    return msg


async def sync_account(session: AsyncSession, client: httpx.AsyncClient, settings: Settings, account: GmailAccount) -> dict:
    """Check one user's new mail. Returns counts for the screen."""
    summary = {"checked": 0, "job_emails": 0, "updated": 0, "unmatched": 0}
    try:
        gmail = await open_gmail(client, settings, account)
        try:
            ids, latest = await gmail.new_inbox_ids(account.history_id) if account.history_id else ([], None)
            if latest is None:
                raise HistoryExpired()
        except HistoryExpired:
            since = account.last_sync_at or (_aware(account.connected_at) - LOOKBACK)
            ids = await gmail.search_ids(f"in:inbox after:{int(since.timestamp())}")
            latest = (await gmail.profile()).get("historyId")
        done = set((await session.scalars(select(GmailMessage.gmail_id).where(
            GmailMessage.user_id == account.user_id, GmailMessage.gmail_id.in_(ids)))).all()) if ids else set()
        oldest = _aware(account.connected_at) - LOOKBACK
        for mid in ids:
            if mid in done:
                continue
            try:
                mail = await gmail.message(mid)
            except httpx.HTTPStatusError as e:
                if e.response.status_code == 404:
                    continue  # deleted meanwhile
                raise
            summary["checked"] += 1
            if mail.received_at < oldest or mail.sender_email == account.email.lower():
                continue
            msg = await handle(session, gmail, account, mail)
            if msg:
                summary["job_emails"] += 1
                summary["unmatched" if msg.action == "unmatched" else "updated"] += 1
            await session.commit()
        account.history_id = latest
        account.last_error = ""
    except oauth.GmailAuthError as e:
        account.last_error = str(e)
    except httpx.HTTPError as e:
        account.last_error = f"Gmail check failed ({e.__class__.__name__}); it will try again"
        log.warning("gmail sync user=%s failed: %r", account.user_id, e)
    account.last_sync_at = datetime.now(timezone.utc)
    await session.commit()
    return summary


async def sync_all(maker: async_sessionmaker, client: httpx.AsyncClient | None = None) -> dict:
    settings = get_settings()
    if not settings.google_client_secret:
        return {}
    own = client is None
    client = client or httpx.AsyncClient()
    results = {}
    try:
        async with maker() as session:
            for account in (await session.scalars(select(GmailAccount))).all():
                if account.last_error.startswith("Gmail access was removed"):
                    continue  # waits for the user to connect again
                results[account.user_id] = await sync_account(session, client, settings, account)
    finally:
        if own:
            await client.aclose()
    log.info("gmail sync %s", results)
    return results


async def undo(session: AsyncSession, gmail: Gmail | None, msg: GmailMessage) -> None:
    """Put things back: email to the Inbox, previous status, and remove a job the email created."""
    job = await session.scalar(select(Job).where(Job.id == msg.job_id, Job.user_id == msg.user_id)
                               .options(selectinload(Job.events))) if msg.job_id else None
    if gmail and msg.moved:
        account = await session.get(GmailAccount, msg.user_id)
        await gmail.modify(msg.gmail_id, add=["INBOX"], remove=[account.label_id] if account and account.label_id else [])
        msg.moved = False
    if job is not None:
        if msg.action == "created_job":
            await session.delete(job)
        else:
            if msg.previous_status and job.status != msg.previous_status:
                job.status = msg.previous_status
                if msg.kind == CONFIRMATION:
                    job.applied_at = job.follow_up_on = None
                job.events.append(Event(kind="status", text=f"{_TO[msg.kind]} → {msg.previous_status} (email undone)"))
            job.updated_at = datetime.now(timezone.utc)
    msg.action = "undone"
    msg.job_id = None
