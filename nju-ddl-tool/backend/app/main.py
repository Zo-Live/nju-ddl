import asyncio
import logging
import os
from contextlib import asynccontextmanager
from datetime import datetime, timezone

from fastapi import Depends, FastAPI, Header, HTTPException, status
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from .config import get_settings
from .db import SessionLocal, get_db, init_db
from .models import ApiSession, Assignment, PlatformSession, User
from .platforms.base import PlatformFetchError
from .platforms.registry import ADAPTERS, get_adapter
from .schemas import (
    AssignmentImport,
    AssignmentOut,
    AuthResponse,
    BrowserLoginStart,
    BrowserLoginStatus,
    CompletionUpdate,
    PlatformInfo,
    UserCreate,
    UserLogin,
)
from .security import create_token, decrypt_json, encrypt_json, hash_password, hash_token, verify_password
from .services.assignments import effective_status, upsert_assignment
from .services.auth import get_current_user
from .services.browser_login import BrowserLoginUnavailable, browser_login_manager


settings = get_settings()
logger = logging.getLogger(__name__)


async def _refresh_all_platforms() -> None:
    interval_min = int(os.getenv("NJU_DDL_REFRESH_INTERVAL_MINUTES", "30"))
    initial_delay_s = int(os.getenv("NJU_DDL_REFRESH_INITIAL_DELAY_SECONDS", "60"))

    await asyncio.sleep(initial_delay_s)

    while True:
        db = SessionLocal()
        try:
            sessions = db.scalars(
                select(PlatformSession).where(
                    PlatformSession.login_state == "connected",
                    PlatformSession.encrypted_storage_state.isnot(None),
                )
            ).all()

            for ps in sessions:
                try:
                    adapter = get_adapter(ps.platform_id)
                    storage_state = decrypt_json(ps.encrypted_storage_state)
                    items = await adapter.fetch_assignments(storage_state)
                    for item in items:
                        upsert_assignment(db, ps.user_id, item)
                    ps.last_refresh_at = datetime.now(timezone.utc)
                    ps.last_error = None
                    db.commit()
                    logger.info("Background refresh: %d items from %s for user %d",
                                len(items), ps.platform_id, ps.user_id)
                except Exception as exc:
                    ps.last_error = str(exc)[:500]
                    try:
                        db.commit()
                    except Exception:
                        db.rollback()
                    logger.warning("Background refresh failed for %s user %d: %s",
                                   ps.platform_id, ps.user_id, exc)

                await asyncio.sleep(10)

        except Exception as exc:
            logger.error("Background refresh cycle error: %s", exc)
        finally:
            db.close()

        await asyncio.sleep(interval_min * 60)


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    refresh_task = asyncio.create_task(_refresh_all_platforms())
    yield
    refresh_task.cancel()
    try:
        await refresh_task
    except asyncio.CancelledError:
        pass
    await browser_login_manager.shutdown()


app = FastAPI(title=settings.app_name, lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


def serialize_assignment(assignment: Assignment) -> AssignmentOut:
    return AssignmentOut(
        id=assignment.id,
        platform_id=assignment.platform_id,
        platform_course_id=assignment.platform_course_id,
        course_name=assignment.course_name,
        platform_assignment_id=assignment.platform_assignment_id,
        title=assignment.title,
        description=assignment.description,
        deadline=assignment.deadline,
        published_at=assignment.published_at,
        remote_status=assignment.remote_status,
        manual_status=assignment.manual_status,
        effective_status=effective_status(assignment),
        source_url=assignment.source_url,
        last_seen_at=assignment.last_seen_at,
    )


def get_or_create_platform_session(db: Session, user_id: int, platform_id: str) -> PlatformSession:
    session = db.scalar(
        select(PlatformSession).where(
            PlatformSession.user_id == user_id,
            PlatformSession.platform_id == platform_id,
        )
    )
    if session is None:
        session = PlatformSession(user_id=user_id, platform_id=platform_id)
        db.add(session)
        db.commit()
        db.refresh(session)
    return session


@app.get("/api/health")
def health() -> dict:
    return {"ok": True}


@app.post("/api/auth/register", response_model=AuthResponse)
def register(payload: UserCreate, db: Session = Depends(get_db)) -> AuthResponse:
    existing = db.scalar(select(User).where(User.username == payload.username))
    if existing is not None:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Username already exists")

    user = User(username=payload.username, password_hash=hash_password(payload.password))
    db.add(user)
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Username already exists") from exc
    db.refresh(user)

    token = create_token()
    db.add(ApiSession(user_id=user.id, token_hash=hash_token(token)))
    db.commit()
    return AuthResponse(token=token, username=user.username)


@app.post("/api/auth/login", response_model=AuthResponse)
def login(payload: UserLogin, db: Session = Depends(get_db)) -> AuthResponse:
    user = db.scalar(select(User).where(User.username == payload.username))
    if user is None or not verify_password(payload.password, user.password_hash):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid username or password")

    token = create_token()
    db.add(ApiSession(user_id=user.id, token_hash=hash_token(token)))
    db.commit()
    return AuthResponse(token=token, username=user.username)


@app.post("/api/auth/logout")
def logout(
    authorization: str | None = Header(default=None),
    db: Session = Depends(get_db),
) -> dict:
    if authorization and authorization.startswith("Bearer "):
        token = authorization.removeprefix("Bearer ").strip()
        session = db.scalar(
            select(ApiSession).where(ApiSession.token_hash == hash_token(token))
        )
        if session is not None:
            db.delete(session)
            db.commit()
    return {"ok": True}


@app.get("/api/platforms", response_model=list[PlatformInfo])
def list_platforms(
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> list[PlatformInfo]:
    rows: list[PlatformInfo] = []
    for adapter in ADAPTERS.values():
        session = db.scalar(
            select(PlatformSession).where(
                PlatformSession.user_id == user.id,
                PlatformSession.platform_id == adapter.id,
            )
        )
        rows.append(
            PlatformInfo(
                id=adapter.id,
                name=adapter.name,
                login_url=adapter.login_url,
                connected=bool(session and session.encrypted_storage_state),
                login_state=session.login_state if session else "not_connected",
                last_login_at=session.last_login_at if session else None,
                last_refresh_at=session.last_refresh_at if session else None,
                last_error=session.last_error if session else None,
            )
        )
    return rows


@app.post("/api/platforms/{platform_id}/login/start", response_model=BrowserLoginStart)
async def start_platform_login(
    platform_id: str,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> BrowserLoginStart:
    try:
        adapter = get_adapter(platform_id)
    except ValueError:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Unknown platform: {platform_id}")
    session = get_or_create_platform_session(db, user.id, platform_id)
    session.login_state = "login_required"
    session.last_error = None
    db.commit()

    try:
        login_session = await browser_login_manager.start(user.id, adapter)
    except BrowserLoginUnavailable as exc:
        session.login_state = "login_unavailable"
        session.last_error = str(exc)
        db.commit()
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(exc)) from exc
    return BrowserLoginStart(
        login_id=login_session.id,
        platform_id=platform_id,
        login_url=adapter.login_url,
        message=(
            "A browser login session was started. Complete the platform login in that browser, "
            "then call the status endpoint until it reports complete."
        ),
    )


@app.get("/api/platforms/{platform_id}/login/{login_id}", response_model=BrowserLoginStatus)
async def check_platform_login(
    platform_id: str,
    login_id: str,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> BrowserLoginStatus:
    login_session = browser_login_manager.get(login_id)
    if login_session is None or login_session.user_id != user.id or login_session.platform_id != platform_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Login session not found")

    state, current_url, storage_state = await browser_login_manager.check_and_save_state(login_id)
    platform_session = get_or_create_platform_session(db, user.id, platform_id)
    if state == "complete" and storage_state is not None:
        platform_session.encrypted_storage_state = encrypt_json(storage_state)
        platform_session.login_state = "connected"
        platform_session.last_login_at = datetime.now(timezone.utc)
        platform_session.last_error = None
        db.commit()
    return BrowserLoginStatus(login_id=login_id, platform_id=platform_id, status=state, current_url=current_url)


@app.delete("/api/platforms/{platform_id}")
def delete_platform_session(
    platform_id: str,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict:
    session = db.scalar(
        select(PlatformSession).where(
            PlatformSession.user_id == user.id,
            PlatformSession.platform_id == platform_id,
        )
    )
    if session is not None:
        session.encrypted_storage_state = None
        session.login_state = "not_connected"
        session.last_error = None
        db.commit()
    return {"ok": True}


@app.post("/api/platforms/{platform_id}/refresh")
async def refresh_platform(
    platform_id: str,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict:
    try:
        adapter = get_adapter(platform_id)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Unknown platform: {platform_id}") from exc
    platform_session = get_or_create_platform_session(db, user.id, platform_id)
    if not platform_session.encrypted_storage_state:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Platform is not connected")

    try:
        storage_state = decrypt_json(platform_session.encrypted_storage_state)
        items = await adapter.fetch_assignments(storage_state)
        for item in items:
            upsert_assignment(db, user.id, item)
        platform_session.last_refresh_at = datetime.now(timezone.utc)
        platform_session.login_state = "connected"
        platform_session.last_error = None
        db.commit()
        return {"ok": True, "count": len(items)}
    except PlatformFetchError as exc:
        platform_session.last_error = str(exc)
        db.commit()
        raise HTTPException(status_code=status.HTTP_501_NOT_IMPLEMENTED, detail=str(exc)) from exc
    except Exception as exc:
        platform_session.last_error = "Refresh failed"
        db.commit()
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail="Refresh failed") from exc


@app.get("/api/assignments", response_model=list[AssignmentOut])
def list_assignments(
    include_completed: bool = False,
    platform_id: str | None = None,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> list[AssignmentOut]:
    stmt = select(Assignment).where(Assignment.user_id == user.id)
    if platform_id:
        stmt = stmt.where(Assignment.platform_id == platform_id)
    rows = list(db.scalars(stmt).all())
    if not include_completed:
        rows = [row for row in rows if effective_status(row) != "completed"]
    rows.sort(key=lambda row: (row.deadline is None, row.deadline or datetime.max.replace(tzinfo=timezone.utc)))
    return [serialize_assignment(row) for row in rows]


@app.post("/api/assignments/import", response_model=AssignmentOut)
def import_assignment(
    payload: AssignmentImport,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> AssignmentOut:
    if payload.platform_id not in ADAPTERS:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Unknown platform")
    assignment = upsert_assignment(db, user.id, payload)
    db.commit()
    db.refresh(assignment)
    return serialize_assignment(assignment)


@app.post("/api/assignments/{assignment_id}/completion", response_model=AssignmentOut)
def set_assignment_completion(
    assignment_id: int,
    payload: CompletionUpdate,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> AssignmentOut:
    assignment = db.scalar(select(Assignment).where(Assignment.id == assignment_id, Assignment.user_id == user.id))
    if assignment is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Assignment not found")
    assignment.manual_status = "completed" if payload.completed else None
    db.commit()
    db.refresh(assignment)
    return serialize_assignment(assignment)
