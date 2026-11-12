import re
import unicodedata

_COMPANY_SUFFIXES = re.compile(
    r"\b(ltd|inc|llc|corp|corporation|gmbh|co|limited|technologies|tech|com|group|holdings|israel|il)\b\.?", re.I
)
_PREVIOUSLY = re.compile(r"\((?:previously|formerly|was)\b[^)]*\)", re.I)  # "CaliAlfa (Previously Alfabet)"
_NON_WORD = re.compile(r"[^\w]+", re.UNICODE)


def _norm(text: str) -> str:
    text = unicodedata.normalize("NFKC", text or "").lower()
    return _NON_WORD.sub(" ", text).strip()


def company_key(company: str) -> str:
    """'Wix.com, Inc.' / 'Wix' -> 'wix'"""
    return _norm(_COMPANY_SUFFIXES.sub(" ", _PREVIOUSLY.sub("", company or "")))


def dedup_key(title: str, company: str, location: str) -> str:
    """Normalized company|title|city key used to merge the same job from different sources."""
    city = _norm((location or "").split(",")[0])
    return f"{company_key(company)}|{_norm(title)}|{city}"


def loose_key(title: str, company: str) -> str:
    """company|title without the city: a candidate duplicate, confirmed by distance (see ingest)."""
    return f"{company_key(company)}|{_norm(title)}"
