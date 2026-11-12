from datetime import date, datetime, timezone
from enum import StrEnum

from sqlalchemy import JSON, Boolean, Date, DateTime, Float, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Status(StrEnum):
    new = "new"
    saved = "saved"
    applied = "applied"
    screening = "screening"
    interview = "interview"
    offer = "offer"
    rejected = "rejected"
    ghosted = "ghosted"
    archived = "archived"


class WorkMode(StrEnum):
    onsite = "onsite"
    hybrid = "hybrid"
    remote = "remote"
    unknown = "unknown"


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    email: Mapped[str] = mapped_column(String(320), unique=True, index=True)  # stored lowercased
    name: Mapped[str] = mapped_column(String(200), default="")
    picture: Mapped[str | None] = mapped_column(Text)
    password_hash: Mapped[str | None] = mapped_column(String(255))  # None = Google-only account
    google_sub: Mapped[str | None] = mapped_column(String(64), unique=True)
    email_verified: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class Job(Base):
    __tablename__ = "jobs"
    __table_args__ = (UniqueConstraint("user_id", "posting_key", name="uq_jobs_user_posting"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    source: Mapped[str] = mapped_column(String(40), default="manual")
    external_id: Mapped[str | None] = mapped_column(String(255))
    url: Mapped[str | None] = mapped_column(Text)
    title: Mapped[str] = mapped_column(String(300))
    company: Mapped[str] = mapped_column(String(200), default="")
    location: Mapped[str] = mapped_column(String(200), default="")
    work_mode: Mapped[str] = mapped_column(String(20), default=WorkMode.unknown)
    description: Mapped[str] = mapped_column(Text, default="")
    salary: Mapped[str | None] = mapped_column(String(120))
    posted_at: Mapped[date | None] = mapped_column(Date)
    dedup_key: Mapped[str] = mapped_column(String(400), index=True)
    parse_issues: Mapped[str] = mapped_column(Text, default="")  # newline-separated import problems
    # Set for jobs found by collectors: "<source>:<external id>", unique per user
    posting_key: Mapped[str | None] = mapped_column(String(300), index=True)
    lat: Mapped[float | None] = mapped_column(Float)
    lon: Mapped[float | None] = mapped_column(Float)
    distance_km: Mapped[float | None] = mapped_column(Float)

    # Tracker fields
    status: Mapped[str] = mapped_column(String(20), default=Status.saved, index=True)
    applied_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    follow_up_on: Mapped[date | None] = mapped_column(Date)
    notes: Mapped[str] = mapped_column(Text, default="")
    contact: Mapped[str] = mapped_column(String(300), default="")

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)

    events: Mapped[list["Event"]] = relationship(
        back_populates="job", cascade="all, delete-orphan", order_by="Event.created_at.desc()"
    )


DEFAULT_TITLES = ["data engineer", "data platform", "big data", "data infrastructure", "analytics engineer"]
DEFAULT_EXCLUDE = ["junior", "intern", "student", "graduate"]


class UserSettings(Base):
    """Each user's job-search preferences."""

    __tablename__ = "user_settings"

    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), primary_key=True)
    home_label: Mapped[str] = mapped_column(String(300), default="")
    home_lat: Mapped[float | None] = mapped_column(Float)
    home_lon: Mapped[float | None] = mapped_column(Float)
    work_modes: Mapped[list] = mapped_column(JSON, default=lambda: ["onsite", "hybrid", "remote"])
    max_km_onsite: Mapped[int] = mapped_column(Integer, default=25)
    max_km_hybrid: Mapped[int] = mapped_column(Integer, default=40)
    title_keywords: Mapped[list] = mapped_column(JSON, default=lambda: list(DEFAULT_TITLES))
    exclude_keywords: Mapped[list] = mapped_column(JSON, default=lambda: list(DEFAULT_EXCLUDE))
    senior_only: Mapped[bool] = mapped_column(Boolean, default=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)


class Company(Base):
    """Company job boards collected for everyone. Starter list + boards users add."""

    __tablename__ = "companies"
    __table_args__ = (UniqueConstraint("ats", "slug"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    ats: Mapped[str] = mapped_column(String(20))  # greenhouse | lever | ashby
    slug: Mapped[str] = mapped_column(String(120))
    name: Mapped[str] = mapped_column(String(200))
    added_by: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    last_ok_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_error: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class GeoCache(Base):
    __tablename__ = "geo_cache"

    query: Mapped[str] = mapped_column(String(300), primary_key=True)  # normalized place text
    lat: Mapped[float | None] = mapped_column(Float)  # None = looked up, not found
    lon: Mapped[float | None] = mapped_column(Float)
    label: Mapped[str] = mapped_column(String(300), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class SearchCache(Base):
    """JSearch results per query, shared by all users to save the monthly quota."""

    __tablename__ = "search_cache"

    query: Mapped[str] = mapped_column(String(300), primary_key=True)
    results: Mapped[list] = mapped_column(JSON, default=list)
    quota_remaining: Mapped[int | None] = mapped_column(Integer)
    fetched_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class CollectionRun(Base):
    __tablename__ = "collection_runs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)  # None = scheduled
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    added: Mapped[int] = mapped_column(Integer, default=0)
    seen: Mapped[int] = mapped_column(Integer, default=0)
    errors: Mapped[str] = mapped_column(Text, default="")


class Event(Base):
    """Timeline entry for a job: status change, note, email (later), etc."""

    __tablename__ = "events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    job_id: Mapped[int] = mapped_column(ForeignKey("jobs.id", ondelete="CASCADE"), index=True)
    kind: Mapped[str] = mapped_column(String(30))  # created | status | note | email
    text: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    job: Mapped[Job] = relationship(back_populates="events")
