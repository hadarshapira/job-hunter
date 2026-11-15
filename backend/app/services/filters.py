"""Decide whether a collected job fits a user's settings."""

import re
from dataclasses import dataclass

from app.models import UserSettings, WorkMode

_SENIOR = re.compile(
    r"\b(senior|sr\.?|staff|lead|principal|head|architect|expert|tech lead|team lead)\b|בכיר|ראש צוות|מוביל", re.I)

# Hebrew title words -> the English word they stand for, so English search phrases also match
# Hebrew postings ("מהנדס/ת דאטה" counts as "data engineer")
_HEBREW = {
    "דאטה": "data", "נתונים": "data", "הנדסת": "engineering", "מהנדס": "engineer", "מהנדסת": "engineer",
    "מפתח": "developer", "מפתחת": "developer", "ביג": "big", "פלטפורמה": "platform", "פלטפורמת": "platform",
    "תשתיות": "infrastructure", "תשתית": "infrastructure", "אנליטיקה": "analytics", "ארכיטקט": "architect",
    "בכיר": "senior", "בכירה": "senior",
}


def _norm(text: str) -> str:
    return re.sub(r"[^\w]+", " ", (text or "").lower()).strip()


def _title_words(title: str) -> list[str]:
    words = []
    for w in _norm(title).split():
        words.append(w)
        # Hebrew words often carry a one-letter prefix: ו (and), ה (the), ל (to), ב (in)
        for cand in (w, w[1:] if len(w) > 3 and w[0] in "והלב" else w):
            if cand in _HEBREW:
                words.append(_HEBREW[cand])
    return words


def _word_in(kw_word: str, words: list[str]) -> bool:
    # Same word, or the same word with a common English ending: "engineer" ~ "engineering"/"engineers".
    # Other longer words don't count ("data" never matches "database").
    for w in words:
        if w == kw_word:
            return True
        if len(kw_word) >= 4 and w.startswith(kw_word) and w[len(kw_word):] in {"s", "ing", "ings", "er", "ers", "ed"}:
            return True
    return False


def title_matches(title: str, keywords: list[str], exclude: list[str], senior_only: bool) -> bool:
    t = _norm(title)
    if any(_norm(x) and re.search(rf"\b{re.escape(_norm(x))}(s|ship|ships)?\b", t) for x in exclude):
        return False
    if senior_only and not _SENIOR.search(title or ""):
        return False
    words = _title_words(title)
    # Every word of a keyword phrase must appear, in any order: "data engineer" matches "Engineer, Data Platform",
    # "Data Engineering Team Lead" and "מהנדס/ת דאטה"
    return any(kw_words and all(_word_in(w, words) for w in kw_words) for kw_words in (_norm(k).split() for k in keywords))


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
