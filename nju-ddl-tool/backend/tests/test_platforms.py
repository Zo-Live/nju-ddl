from types import SimpleNamespace
from uuid import uuid4

from sqlalchemy import select

from app.main import get_or_create_platform_session
from app.models import Assignment, Course, User
from app.platforms.base import NormalizedAssignment
from app.security import encrypt_json
from app.services.browser_login import BrowserLoginUnavailable


class TestPlatforms:
    def test_list_platforms(self, client, auth_headers):
        resp = client.get("/api/platforms", headers=auth_headers)
        assert resp.status_code == 200
        data = resp.json()
        assert isinstance(data, list)
        ids = {p["id"] for p in data}
        assert ids == {"educoder", "nju_lms", "cslab_cms"}

    def test_list_platforms_unauthorized(self, client):
        resp = client.get("/api/platforms")
        assert resp.status_code == 401

    def test_login_start(self, client, auth_headers, monkeypatch):
        async def fake_start(user_id, adapter):
            return SimpleNamespace(id="login-id", user_id=user_id, platform_id=adapter.id)

        monkeypatch.setattr("app.main.browser_login_manager.start", fake_start)
        resp = client.post("/api/platforms/educoder/login/start", headers=auth_headers)
        assert resp.status_code == 200
        data = resp.json()
        assert data["platform_id"] == "educoder"
        assert data["login_id"] == "login-id"

    def test_login_start_unavailable_returns_503(self, client, auth_headers, monkeypatch):
        async def fake_start(_user_id, _adapter):
            raise BrowserLoginUnavailable("平台登录需要可见浏览器")

        monkeypatch.setattr("app.main.browser_login_manager.start", fake_start)
        resp = client.post("/api/platforms/educoder/login/start", headers=auth_headers)
        assert resp.status_code == 503
        assert resp.json()["detail"] == "平台登录需要可见浏览器"

        platforms = client.get("/api/platforms", headers=auth_headers).json()
        educoder = next(platform for platform in platforms if platform["id"] == "educoder")
        assert educoder["login_state"] == "login_unavailable"
        assert educoder["last_error"] == "平台登录需要可见浏览器"

    def test_login_check_missing_session(self, client, auth_headers):
        resp = client.get("/api/platforms/educoder/login/nonexistent", headers=auth_headers)
        assert resp.status_code == 404

    def test_delete_not_connected(self, client, auth_headers):
        resp = client.delete("/api/platforms/educoder", headers=auth_headers)
        assert resp.status_code == 200
        assert resp.json()["ok"] is True

    def test_refresh_unconnected(self, client, auth_headers):
        resp = client.post("/api/platforms/educoder/refresh", headers=auth_headers)
        assert resp.status_code == 409

    def test_refresh_unknown_platform(self, client, auth_headers):
        resp = client.post("/api/platforms/xyz/refresh", headers=auth_headers)
        assert resp.status_code == 404

    def test_refresh_imports_multiple_assignments_from_same_course(
        self,
        client,
        auth_headers,
        db_session,
        monkeypatch,
    ):
        user = db_session.scalar(select(User).where(User.username == "testuser"))
        platform_session = get_or_create_platform_session(db_session, user.id, "educoder")
        platform_session.encrypted_storage_state = encrypt_json({"cookies": []})
        platform_session.login_state = "connected"
        platform_session.last_error = None
        db_session.commit()

        course_id = f"course-{uuid4()}"
        items = [
            NormalizedAssignment(
                platform_id="educoder",
                platform_course_id=course_id,
                course_name="测试课程",
                platform_assignment_id=f"hw-{uuid4()}",
                title="第一份作业",
            ),
            NormalizedAssignment(
                platform_id="educoder",
                platform_course_id=course_id,
                course_name="测试课程",
                platform_assignment_id=f"hw-{uuid4()}",
                title="第二份作业",
            ),
        ]

        class FakeAdapter:
            id = "educoder"

            async def fetch_assignments(self, _storage_state):
                return items

        monkeypatch.setattr("app.main.get_adapter", lambda _platform_id: FakeAdapter())

        resp = client.post("/api/platforms/educoder/refresh", headers=auth_headers)

        assert resp.status_code == 200, resp.text
        assert resp.json()["count"] == 2
        courses = db_session.scalars(
            select(Course).where(
                Course.user_id == user.id,
                Course.platform_id == "educoder",
                Course.platform_course_id == course_id,
            )
        ).all()
        assignments = db_session.scalars(
            select(Assignment).where(
                Assignment.user_id == user.id,
                Assignment.platform_id == "educoder",
                Assignment.platform_course_id == course_id,
            )
        ).all()
        assert len(courses) == 1
        assert {assignment.title for assignment in assignments} == {"第一份作业", "第二份作业"}

    def test_unknown_platform(self, client, auth_headers):
        resp = client.post("/api/platforms/xyz/login/start", headers=auth_headers)
        assert resp.status_code == 404
