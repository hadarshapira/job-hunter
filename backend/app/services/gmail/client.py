"""Small Gmail API client: searching the Inbox, reading a message, labels."""

import base64
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from email.utils import parseaddr

import httpx
from selectolax.lexbor import LexborHTMLParser

API = "https://gmail.googleapis.com/gmail/v1/users/me"


@dataclass
class Mail:
    id: str
    thread_id: str
    sender_name: str
    sender_email: str
    subject: str
    text: str
    received_at: datetime
    labels: list[str]

    @property
    def sender_domain(self) -> str:
        return self.sender_email.rsplit("@", 1)[-1].lower() if "@" in self.sender_email else ""


def _b64(data: str) -> bytes:
    return base64.urlsafe_b64decode(data + "=" * (-len(data) % 4))


def _html_text(html: str) -> str:
    tree = LexborHTMLParser(html)
    for n in tree.css("style, script, head"):
        n.decompose()
    body = tree.body or tree.root
    return body.text(separator="\n") if body else ""


def _body(payload: dict) -> str:
    """Plain text of a message: the text/plain part if there is one, else the HTML part as text."""
    plain, html = [], []

    def walk(part: dict) -> None:
        mime = part.get("mimeType", "")
        data = (part.get("body") or {}).get("data")
        if data and mime == "text/plain":
            plain.append(_b64(data).decode("utf-8", "replace"))
        elif data and mime == "text/html":
            html.append(_b64(data).decode("utf-8", "replace"))
        for p in part.get("parts") or []:
            walk(p)

    walk(payload)
    text = "\n".join(plain) if plain else "\n".join(_html_text(h) for h in html)
    return re.sub(r"\n\s*\n+", "\n\n", text).strip()


def parse_message(m: dict) -> Mail:
    headers = {h["name"].lower(): h["value"] for h in (m.get("payload") or {}).get("headers", [])}
    name, addr = parseaddr(headers.get("from", ""))
    received = datetime.fromtimestamp(int(m.get("internalDate", "0")) / 1000, timezone.utc)
    return Mail(
        id=m["id"], thread_id=m.get("threadId", ""), sender_name=name.strip().strip('"'), sender_email=addr.lower(),
        subject=" ".join(headers.get("subject", "").split()), text=_body(m.get("payload") or {}),
        received_at=received, labels=m.get("labelIds", []),
    )


class Gmail:
    def __init__(self, client: httpx.AsyncClient, token: str):
        self.client = client
        self.headers = {"Authorization": f"Bearer {token}"}
        self._label_ids: dict[str, str] | None = None  # label name -> id, read once per check

    async def _req(self, method: str, path: str, **kw) -> dict:
        r = await self.client.request(method, f"{API}{path}", headers=self.headers, timeout=30, **kw)
        r.raise_for_status()
        return r.json() if r.content else {}

    async def profile(self) -> dict:
        return await self._req("GET", "/profile")

    async def search_ids(self, query: str, limit: int = 500) -> list[str]:
        ids: list[str] = []
        params = {"q": query, "maxResults": min(limit, 500)}
        while True:
            data = await self._req("GET", "/messages", params=params)
            ids += [m["id"] for m in data.get("messages", [])]
            if len(ids) >= limit or not data.get("nextPageToken"):
                return ids[:limit]
            params["pageToken"] = data["nextPageToken"]

    async def message(self, message_id: str) -> Mail:
        return parse_message(await self._req("GET", f"/messages/{message_id}", params={"format": "full"}))

    async def _labels(self) -> dict[str, str]:
        if self._label_ids is None:
            self._label_ids = {lb["name"]: lb["id"] for lb in (await self._req("GET", "/labels")).get("labels", [])}
        return self._label_ids

    def forget_labels(self) -> None:
        self._label_ids = None

    async def existing_label_ids(self, names: list[str]) -> list[str]:
        labels = await self._labels()
        return [labels[n] for n in names if n in labels]

    async def label_id(self, name: str) -> str:
        """Id of the label with this name, created if it doesn't exist. "A/B" is label B nested under A."""
        labels = await self._labels()
        if name in labels:
            return labels[name]
        if "/" in name:
            await self.label_id(name.rsplit("/", 1)[0])  # Gmail shows "A/B" nested only when "A" exists
        created = await self._req("POST", "/labels", json={
            "name": name, "labelListVisibility": "labelShow", "messageListVisibility": "show"})
        labels[name] = created["id"]
        return created["id"]

    async def modify(self, message_id: str, add: list[str], remove: list[str]) -> None:
        await self._req("POST", f"/messages/{message_id}/modify", json={"addLabelIds": add, "removeLabelIds": remove})
