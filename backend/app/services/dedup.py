import re
import unicodedata

_COMPANY_SUFFIXES = re.compile(r"\b(ltd|inc|llc|corp|corporation|gmbh|co|limited|technologies|tech)\b\.?", re.I)
_NON_WORD = re.compile(r"[^\w]+", re.UNICODE)


def _norm(text: str) -> str:
    text = unicodedata.normalize("NFKC", text or "").lower()
    return _NON_WORD.sub(" ", text).strip()


def dedup_key(title: str, company: str, location: str) -> str:
    """Normalized company|title|city key used to merge the same job from different sources."""
    company_n = _norm(_COMPANY_SUFFIXES.sub("", company or ""))
    title_n = _norm(title)
    city = _norm((location or "").split(",")[0])
    return f"{company_n}|{title_n}|{city}"
