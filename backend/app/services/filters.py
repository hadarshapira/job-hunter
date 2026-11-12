"""Decide whether a collected job fits a user's settings."""

import re
from dataclasses import dataclass

from app.models import UserSettings, WorkMode

_SENIOR = re.compile(r"\b(senior|sr\.?|staff|lead|principal|head|architect|expert|tech lead|team lead)\b", re.I)


def _norm(text: str) -> str:
    return re.sub(r"[^\w]+", " ", (text or "").lower()).strip()


def title_matches(title: str, keywords: list[str], exclude: list[str], senior_only: bool) -> bool:
    t = _norm(title)
    words = set(t.split())
    if any(_norm(x) and re.search(rf"\b{re.escape(_norm(x))}\b", t) for x in exclude):
        return False
    if senior_only and not _SENIOR.search(title or ""):
        return False
    # Every word of a keyword phrase must appear: "data engineer" matches "Engineer, Data Platform"
    return any(kw_words and set(kw_words) <= words for kw_words in (_norm(k).split() for k in keywords))


@dataclass
class Decision:
    ok: bool
    reason: str = ""
    distance_km: float | None = None


def location_decision(s: UserSettings, work_mode: str, distance_km: float | None) -> Decision:
    modes = set(s.work_modes or [])
    if work_mode == WorkMode.remote:
        return Decision("remote" in modes, "" if "remote" in modes else "remote not wanted", distance_km)

    # On-site, hybrid, or unknown (treated as either, so a good job isn't lost to a missing label)
    allowed = {WorkMode.onsite: ["onsite"], WorkMode.hybrid: ["hybrid"]}.get(work_mode, ["onsite", "hybrid"])
    allowed = [m for m in allowed if m in modes]
    if not allowed:
        return Decision(False, f"{work_mode} not wanted", distance_km)
    if distance_km is None or s.home_lat is None:
        return Decision(True, "distance unknown", distance_km)  # keep it; the user decides
    limit = max(s.max_km_onsite if m == "onsite" else s.max_km_hybrid for m in allowed)
    if distance_km <= limit:
        return Decision(True, "", distance_km)
    return Decision(False, f"{distance_km:.0f} km away (max {limit})", distance_km)
