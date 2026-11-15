from datetime import date, datetime

from pydantic import BaseModel, ConfigDict, EmailStr, Field, HttpUrl

from app.models import Status, WorkMode


class EventOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    kind: str
    text: str
    created_at: datetime


class JobBase(BaseModel):
    title: str = Field(min_length=1, max_length=300)
    company: str = ""
    location: str = ""
    work_mode: WorkMode = WorkMode.unknown
    description: str = ""
    salary: str | None = None
    url: str | None = None
    posted_at: date | None = None


class JobCreate(JobBase):
    status: Status = Status.saved


class JobUpdate(BaseModel):
    title: str | None = None
    company: str | None = None
    location: str | None = None
    work_mode: WorkMode | None = None
    description: str | None = None
    salary: str | None = None
    status: Status | None = None
    follow_up_on: date | None = None
    notes: str | None = None
    contact: str | None = None


class JobSummary(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    title: str
    company: str
    location: str
    work_mode: str
    source: str
    status: str
    salary: str | None
    url: str | None
    posted_at: date | None
    applied_at: datetime | None
    follow_up_on: date | None
    distance_km: float | None = None
    match_score: int | None = None
    created_at: datetime
    updated_at: datetime


class JobOut(JobSummary):
    description: str
    notes: str
    contact: str
    parse_issues: str = ""
    match: dict | None = None
    match_at: datetime | None = None
    events: list[EventOut] = []


class ImportRequest(BaseModel):
    url: HttpUrl


class ImportResult(BaseModel):
    job: JobOut
    duplicate: bool = False
    complete: bool = True  # False when the page had no structured job data


class NoteCreate(BaseModel):
    text: str = Field(min_length=1)


class LoginRequest(BaseModel):
    email: EmailStr
    password: str = Field(max_length=256)


class SignupRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=8, max_length=256)
    name: str = Field(default="", max_length=200)


class GoogleLogin(BaseModel):
    credential: str = Field(min_length=10, max_length=8000)  # Google ID token (JWT)


class UserOut(BaseModel):
    id: int
    email: str
    name: str
    picture: str | None
    has_password: bool
    google_linked: bool

    @classmethod
    def from_user(cls, u) -> "UserOut":
        return cls(
            id=u.id,
            email=u.email,
            name=u.name,
            picture=u.picture,
            has_password=u.password_hash is not None,
            google_linked=u.google_sub is not None,
        )


class Stats(BaseModel):
    new: int = 0
    by_status: dict[str, int]
    by_source: dict[str, int]
    applied_total: int
    responded: int
    response_rate: float
    follow_ups_due: int
