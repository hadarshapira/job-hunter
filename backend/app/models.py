from datetime import date, datetime, timezone
from enum import StrEnum

from sqlalchemy import Boolean, Date, DateTime, ForeignKey, Integer, String, Text
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


class Event(Base):
    """Timeline entry for a job: status change, note, email (later), etc."""

    __tablename__ = "events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    job_id: Mapped[int] = mapped_column(ForeignKey("jobs.id", ondelete="CASCADE"), index=True)
    kind: Mapped[str] = mapped_column(String(30))  # created | status | note | email
    text: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    job: Mapped[Job] = relationship(back_populates="events")
