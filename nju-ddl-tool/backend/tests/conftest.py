import os
import atexit

os.environ["NJU_DDL_SECRET"] = "test-secret-for-unit-tests"
_db_file = f"/tmp/pytest_nju_ddl_{os.getpid()}.db"
os.environ["NJU_DDL_DATABASE_URL"] = f"sqlite:///{_db_file}"

atexit.register(lambda: os.path.exists(_db_file) and os.remove(_db_file))

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import event

from app.db import Base, engine, get_db, SessionLocal
from app.main import app


@pytest.fixture(autouse=True)
def _ensure_tables():
    @event.listens_for(engine, "connect")
    def _enable_fks(dbapi_connection, _connection_record):
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

    Base.metadata.create_all(bind=engine)


@pytest.fixture
def db_session():
    session = SessionLocal()
    yield session
    session.rollback()
    session.close()


@pytest.fixture
def client(db_session):
    def override_get_db():
        yield db_session

    app.dependency_overrides[get_db] = override_get_db
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()


@pytest.fixture
def auth_token(client):
    client.post("/api/auth/register", json={"username": "testuser", "password": "testpass123"})
    resp = client.post("/api/auth/login", json={"username": "testuser", "password": "testpass123"})
    return resp.json()["token"]


@pytest.fixture
def auth_headers(auth_token):
    return {"Authorization": f"Bearer {auth_token}"}
