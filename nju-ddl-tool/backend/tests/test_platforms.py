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

    def test_login_start(self, client, auth_headers):
        resp = client.post("/api/platforms/educoder/login/start", headers=auth_headers)
        assert resp.status_code == 200
        data = resp.json()
        assert data["platform_id"] == "educoder"
        assert "login_id" in data

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

    def test_unknown_platform(self, client, auth_headers):
        resp = client.post("/api/platforms/xyz/login/start", headers=auth_headers)
        assert resp.status_code == 404
