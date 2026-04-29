from datetime import datetime, timezone

from sqlalchemy import DateTime, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .db import Base


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    username: Mapped[str] = mapped_column(String(128), unique=True, index=True)
    password_hash: Mapped[str] = mapped_column(String(512))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    sessions: Mapped[list["ApiSession"]] = relationship(cascade="all, delete-orphan")


class ApiSession(Base):
    __tablename__ = "api_sessions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    token_hash: Mapped[str] = mapped_column(String(128), unique=True, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    last_seen_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class PlatformSession(Base):
    __tablename__ = "platform_sessions"
    __table_args__ = (UniqueConstraint("user_id", "platform_id", name="uq_user_platform"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    platform_id: Mapped[str] = mapped_column(String(64), index=True)
    encrypted_storage_state: Mapped[str | None] = mapped_column(Text, nullable=True)
    login_state: Mapped[str] = mapped_column(String(32), default="not_connected")
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_refresh_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)


class Course(Base):
    __tablename__ = "courses"
    __table_args__ = (UniqueConstraint("user_id", "platform_id", "platform_course_id", name="uq_user_platform_course"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    platform_id: Mapped[str] = mapped_column(String(64), index=True)
    platform_course_id: Mapped[str] = mapped_column(String(256), index=True)
    name: Mapped[str] = mapped_column(String(512))
    source_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    last_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class Assignment(Base):
    __tablename__ = "assignments"
    __table_args__ = (UniqueConstraint("user_id", "platform_id", "platform_assignment_id", name="uq_user_platform_assignment"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    platform_id: Mapped[str] = mapped_column(String(64), index=True)
    platform_course_id: Mapped[str] = mapped_column(String(256), index=True)
    course_name: Mapped[str] = mapped_column(String(512))
    platform_assignment_id: Mapped[str] = mapped_column(String(512), index=True)
    title: Mapped[str] = mapped_column(String(512))
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    deadline: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    remote_status: Mapped[str] = mapped_column(String(32), default="unknown")
    manual_status: Mapped[str | None] = mapped_column(String(32), nullable=True)
    source_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    last_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
