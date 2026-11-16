"""Import a job from any URL, plus the ParsedJob type and text helpers every source shares.

Order (fetch_and_parse): site extractors (ATS APIs, LinkedIn) -> schema.org JobPosting JSON-LD ->
page title + meta description (flagged incomplete) -> quality check. Details: docs/parsers.md.
"""

import json
import re
from dataclasses import dataclass, field
from datetime import date
from html import unescape

import httpx
from selectolax.lexbor import LexborHTMLParser as HTMLParser

from app.models import WorkMode

USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0 Safari/537.36"


@dataclass
class ParsedJob:
    title: str
    company: str = ""
    location: str = ""
    work_mode: WorkMode = WorkMode.unknown
    description: str = ""
    salary: str | None = None
    posted_at: date | None = None
    complete: bool = True
    extra: dict = field(default_factory=dict)
    issues: list[str] = field(default_factory=list)  # filled by quality.assess()


def html_to_text(html: str) -> str:
    if not html:
        return ""
    if "<" not in html:
        return unescape(html).strip()
    tree = HTMLParser(html)
    for node in tree.css("br"):
        node.replace_with("\n")
    for node in tree.css("p, li, div, h1, h2, h3, h4, tr"):
        node.insert_after("\n")
    for node in tree.css("li"):
        node.insert_before("• ")
    text = tree.text(separator="")
    text = re.sub(r"[ \t\xa0]+", " ", text)
    return re.sub(r"\n\s*\n+", "\n\n", text).strip()


def _iter_jsonld(tree: HTMLParser):
    for node in tree.css('script[type="application/ld+json"]'):
        raw = node.text(strip=True)
        if not raw:
            continue
        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            continue
        stack = [data]
        while stack:
            item = stack.pop()
            if isinstance(item, list):
                stack.extend(item)
            elif isinstance(item, dict):
                yield item
                if "@graph" in item:
                    stack.append(item["@graph"])


def _is_job_posting(item: dict) -> bool:
    t = item.get("@type")
    return t == "JobPosting" or (isinstance(t, list) and "JobPosting" in t)


def _location(posting: dict) -> str:
    locs = posting.get("jobLocation") or []
    if isinstance(locs, dict):
        locs = [locs]
    parts = []
    for loc in locs:
        addr = loc.get("address", {}) if isinstance(loc, dict) else {}
        if isinstance(addr, str):
            parts.append(addr)
            continue
        city = addr.get("addressLocality") or ""
        country = addr.get("addressCountry") or ""
        if isinstance(country, dict):
            country = country.get("name", "")
        label = ", ".join(p for p in (city, country) if p)
        if label and label not in parts:
            parts.append(label)
    return " / ".join(parts)


def _salary(posting: dict) -> str | None:
    base = posting.get("baseSalary")
    if not isinstance(base, dict):
        return None
    cur = base.get("currency", "")
    val = base.get("value", {})
    if isinstance(val, dict):
        lo, hi, unit = val.get("minValue"), val.get("maxValue"), val.get("unitText", "")
        amount = f"{lo}-{hi}" if lo and hi else str(val.get("value") or lo or hi or "")
        return f"{amount} {cur} {unit}".strip() or None
    return f"{val} {cur}".strip() or None


def guess_work_mode(*texts: str) -> WorkMode:
    blob = " ".join(t for t in texts if t).lower()
    # Hebrew: היברידי = hybrid, מהבית / מרחוק = from home / remote, במשרד = in the office
    if re.search(r"\bhybrid\b|היברידי", blob):
        return WorkMode.hybrid
    if re.search(r"\bremote\b|work from home|wfh|מהבית|מרחוק", blob):
        return WorkMode.remote
    if re.search(r"\bon[- ]?site\b|in[- ]office|במשרד", blob):
        return WorkMode.onsite
    return WorkMode.unknown


def _parse_date(value) -> date | None:
    if not value or not isinstance(value, str):
        return None
    try:
        return date.fromisoformat(value[:10])
    except ValueError:
        return None


def parse_job_html(html: str) -> ParsedJob | None:
    tree = HTMLParser(html)
    for item in _iter_jsonld(tree):
        if not _is_job_posting(item):
            continue
        org = item.get("hiringOrganization") or {}
        company = org.get("name", "") if isinstance(org, dict) else str(org)
        description = html_to_text(item.get("description", ""))
        location = _location(item)
        mode = WorkMode.remote if item.get("jobLocationType") == "TELECOMMUTE" else guess_work_mode(
            item.get("title", ""), location, description
        )
        return ParsedJob(
            title=unescape(item.get("title", "")).strip() or "Untitled job",
            company=unescape(company).strip(),
            location=location,
            work_mode=mode,
            description=description,
            salary=_salary(item),
            posted_at=_parse_date(item.get("datePosted")),
        )

    # Fallback: page metadata
    def meta(name: str) -> str:
        node = tree.css_first(f'meta[property="{name}"]') or tree.css_first(f'meta[name="{name}"]')
        return (node.attributes.get("content") or "").strip() if node else ""

    title = meta("og:title") or (tree.css_first("title").text(strip=True) if tree.css_first("title") else "")
    if not title:
        return None
    description = meta("og:description") or meta("description")
    return ParsedJob(
        title=unescape(title),
        company=unescape(meta("og:site_name")),
        description=unescape(description),
        work_mode=guess_work_mode(title, description),
        complete=False,
    )


async def fetch_and_parse(url: str, client: httpx.AsyncClient | None = None) -> ParsedJob:
    """Import pipeline: site extractors → generic HTML (JSON-LD, then page metadata) → quality check."""
    # Local imports: these modules build on helpers in this one
    from app.services.quality import assess
    from app.services.sites import extractors

    own = client is None
    client = client or httpx.AsyncClient(timeout=20, follow_redirects=True, headers={"User-Agent": USER_AGENT})
    try:
        parsed = None
        for name, extract in extractors():
            if parsed := await extract(url, client):
                parsed.extra["extractor"] = name
                break
        if parsed is None:
            resp = await client.get(url)
            resp.raise_for_status()
            parsed = parse_job_html(resp.text) or ParsedJob(title="Imported job (edit details)", complete=False)
            parsed.extra["extractor"] = "jsonld" if parsed.complete else "metadata"
    finally:
        if own:
            await client.aclose()
    parsed, parsed.issues = assess(parsed)
    return parsed
