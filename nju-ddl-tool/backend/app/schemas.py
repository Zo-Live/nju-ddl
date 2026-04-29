from datetime import datetime

from pydantic import BaseModel, Field


class UserCreate(BaseModel):
    username: str = Field(min_length=2, max_length=128)
    password: str = Field(min_length=8, max_length=256)


class UserLogin(BaseModel):
    username: str
    password: str


class AuthResponse(BaseModel):
    token: str
    username: str


class PlatformInfo(BaseModel):
    id: str
    name: str
    login_url: str
    connected: bool
    login_state: str
    last_login_at: datetime | None
    last_refresh_at: datetime | None
    last_error: str | None


class BrowserLoginStart(BaseModel):
    login_id: str
    platform_id: str
    login_url: str
    message: str


class BrowserLoginStatus(BaseModel):
    login_id: str
    platform_id: str
    status: str
    current_url: str | None = None
    detail: str | None = None


class AssignmentOut(BaseModel):
    id: int
    platform_id: str
    platform_course_id: str
    course_name: str
    platform_assignment_id: str
    title: str
    description: str | None
    deadline: datetime | None
    published_at: datetime | None
    remote_status: str
    manual_status: str | None
    effective_status: str
    source_url: str | None
    last_seen_at: datetime


class AssignmentImport(BaseModel):
    platform_id: str
    platform_course_id: str
    course_name: str
    platform_assignment_id: str
    title: str
    description: str | None = None
    deadline: datetime | None = None
    published_at: datetime | None = None
    remote_status: str = "unknown"
    source_url: str | None = None


class CompletionUpdate(BaseModel):
    completed: bool
