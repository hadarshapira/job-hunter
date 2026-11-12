"""Site-specific job extractors.

Each extractor handles one site whose pages don't carry standard schema.org JobPosting data.
They run before the generic HTML parser. To add a site, see docs/parsers.md.
"""

from collections.abc import Awaitable, Callable

import httpx

from app.services.importer import ParsedJob

Extractor = Callable[[str, httpx.AsyncClient], Awaitable[ParsedJob | None]]


def extractors() -> list[tuple[str, Extractor]]:
    # Imported lazily to avoid import cycles (extractors use importer helpers)
    from app.services.ats import resolve_ats
    from app.services.sites.linkedin import extract_linkedin

    return [("ats", resolve_ats), ("linkedin", extract_linkedin)]
