"""Job collectors. Each returns Postings: a ParsedJob plus where it came from."""

from dataclasses import dataclass

from app.services.importer import ParsedJob


@dataclass
class Posting:
    job: ParsedJob
    source: str  # "jsearch" | "greenhouse" | "lever" | "ashby"
    external_id: str
    url: str | None
    lat: float | None = None
    lon: float | None = None
    country: str | None = None  # ISO code when the source tells us

    @property
    def key(self) -> str:
        return f"{self.source}:{self.external_id}"
