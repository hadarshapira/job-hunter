"""Geocoding with OpenStreetMap Nominatim (free), cached in the database, plus distance math.

Nominatim policy: max 1 request/second and an identifying User-Agent. Everything is cached
forever (city names don't move), so after the first few runs almost no requests are made.
No user data is sent: only place names (a user's home text and job city names).
"""

import asyncio
import math
import re
import time
import unicodedata

import httpx
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import GeoCache

NOMINATIM = "https://nominatim.openstreetmap.org/search"
USER_AGENT = "JobHunter/0.1 (self-hosted job search app)"
_lock = asyncio.Lock()
_last_call = 0.0

# Words in job locations that aren't places
_NOISE = re.compile(r"\b(remote|hybrid|on-?site|office|hq|headquarters|israel only|district)\b", re.I)

# Israeli places seen in job locations. Used to decide "is this job in Israel?" without guessing
# from the geocoder (which, limited to Israel, would happily map "New York" to some street in Israel).
ISRAEL_PLACES = [
    "israel", "tel aviv", "tel-aviv", "tlv", "herzliya", "herzelia", "haifa", "jerusalem", "petah tikva", "petach tikva",
    "ramat gan", "givatayim", "ra'anana", "raanana", "kfar saba", "hod hasharon", "netanya", "rehovot", "rishon",
    "ness ziona", "nes ziona", "be'er sheva", "beer sheva", "beersheba", "yokneam", "caesarea", "modi'in", "modiin",
    "rosh ha'ayin", "rosh haayin", "airport city", "or yehuda", "holon", "bat yam", "bnei brak", "yavne", "ashdod",
    "kiryat gat", "ashkelon", "lod", "ramla", "matam", "nazareth", "karmiel", "tirat carmel", "omer", "sderot",
    "shoham", "yehud", "kiryat ono", "rosh pina", "tel aviv-yafo", "jaffa",
    "תל אביב", "ישראל", "הרצליה", "חיפה", "ירושלים", "פתח תקווה", "רמת גן", "רעננה", "כפר סבא", "נתניה", "רחובות",
    "יפו", "יקנעם", "ראש העין", "הוד השרון", "ראשון לציון", "באר שבע", "מודיעין", "נס ציונה", "גבעתיים", "חולון",
    "בני ברק", "אור יהודה", "שוהם", "יהוד", "קיסריה", "נתב\"ג",
]


def mentions_israel(text: str) -> bool:
    text = (text or "").lower()
    return any(p in text for p in ISRAEL_PLACES)


def in_israel(location: str, country: str | None = None) -> bool:
    # Trust "IL", but never trust another country code alone: JSearch labels many Israeli jobs
    # "Tel Aviv-Yafo, US". The place name decides.
    if country and country.upper() in ("IL", "ISR", "ISRAEL"):
        return True
    return mentions_israel(location)


def in_israel_bbox(lat: float | None, lon: float | None) -> bool:
    return lat is not None and lon is not None and 29.4 <= lat <= 33.4 and 34.2 <= lon <= 35.95


def normalize_place(text: str) -> str:
    """'Tel Aviv-Yafo, Tel Aviv District, Israel; New York' -> 'tel aviv-yafo, israel'"""
    text = unicodedata.normalize("NFKC", text or "")
    first = re.split(r"[;/|•]|\bor\b", text)[0]
    first = _NOISE.sub("", first)
    parts = [p.strip(" -()") for p in first.split(",") if p.strip(" -()")]
    if parts and parts[-1].lower() != "israel":
        parts.append("israel")
    if len(parts) > 2:
        parts = [parts[0], parts[-1]]
    return ", ".join(parts).lower()


def haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    r = 6371.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp, dl = math.radians(lat2 - lat1), math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))


async def _nominatim(client: httpx.AsyncClient, query: str) -> tuple[float, float, str] | None:
    global _last_call
    async with _lock:  # 1 request/second for the whole process
        wait = 1.1 - (time.monotonic() - _last_call)
        if wait > 0:
            await asyncio.sleep(wait)
        _last_call = time.monotonic()
        r = await client.get(
            NOMINATIM,
            params={"q": query, "format": "jsonv2", "limit": 1, "countrycodes": "il", "accept-language": "en"},
            headers={"User-Agent": USER_AGENT},
        )
    if r.status_code != 200 or not r.json():
        return None
    hit = r.json()[0]
    return float(hit["lat"]), float(hit["lon"]), hit.get("display_name", "")


async def geocode(session: AsyncSession, client: httpx.AsyncClient, place: str) -> tuple[float, float, str] | None:
    """Look up a place in Israel. Returns (lat, lon, label) or None. Results (also misses) are cached."""
    key = normalize_place(place)
    if not key or key == "israel":
        return None
    cached = await session.get(GeoCache, key)
    if cached:
        return (cached.lat, cached.lon, cached.label) if cached.lat is not None else None
    try:
        hit = await _nominatim(client, key)
    except httpx.HTTPError:
        return None  # don't cache network failures
    session.add(GeoCache(query=key, lat=hit[0] if hit else None, lon=hit[1] if hit else None, label=hit[2] if hit else ""))
    await session.flush()
    return hit
