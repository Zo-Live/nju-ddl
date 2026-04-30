class TestAuth:
    def test_register(self, client):
        resp = client.post("/api/auth/register", json={"username": "u1", "password": "pass12345"})
        assert resp.status_code == 200
        data = resp.json()
        assert "token" in data
        assert data["username"] == "u1"

    def test_register_duplicate(self, client):
        client.post("/api/auth/register", json={"username": "dup", "password": "pass12345"})
        resp = client.post("/api/auth/register", json={"username": "dup", "password": "pass12345"})
        assert resp.status_code == 409

    def test_register_short_password_returns_422(self, client):
        resp = client.post("/api/auth/register", json={"username": "u", "password": "short"})
        assert resp.status_code == 422

    def test_login_ok(self, client):
        client.post("/api/auth/register", json={"username": "ok", "password": "pass12345"})
        resp = client.post("/api/auth/login", json={"username": "ok", "password": "pass12345"})
        assert resp.status_code == 200
        assert resp.json()["username"] == "ok"

    def test_login_wrong_password(self, client):
        client.post("/api/auth/register", json={"username": "pw", "password": "pass12345"})
        resp = client.post("/api/auth/login", json={"username": "pw", "password": "wrong1234"})
        assert resp.status_code == 401

    def test_login_nonexistent_user(self, client):
        resp = client.post("/api/auth/login", json={"username": "nobody", "password": "pass12345"})
        assert resp.status_code == 401

    def test_protected_route_needs_auth(self, client):
        resp = client.get("/api/platforms")
        assert resp.status_code == 401  # no header → 401 (missing bearer token)

    def test_invalid_token(self, client):
        resp = client.get("/api/platforms", headers={"Authorization": "Bearer garbage"})
        assert resp.status_code == 401

    def test_logout_invalidates_token(self, client, auth_token, auth_headers):
        client.post("/api/auth/logout", headers=auth_headers)
        resp = client.get("/api/platforms", headers=auth_headers)
        assert resp.status_code == 401
