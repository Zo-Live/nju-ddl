class TestAssignments:
    def test_empty_list(self, client, auth_headers):
        resp = client.get("/api/assignments", headers=auth_headers)
        assert resp.status_code == 200
        assert resp.json() == []

    def test_import(self, client, auth_headers):
        resp = client.post(
            "/api/assignments/import",
            headers=auth_headers,
            json={
                "platform_id": "educoder",
                "platform_course_id": "42",
                "course_name": "测试课程",
                "platform_assignment_id": "hw1",
                "title": "测试作业",
            },
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["title"] == "测试作业"
        assert data["platform_id"] == "educoder"
        assert data["effective_status"] == "unknown"

    def test_import_unknown_platform(self, client, auth_headers):
        resp = client.post(
            "/api/assignments/import",
            headers=auth_headers,
            json={
                "platform_id": "xyz",
                "platform_course_id": "1",
                "course_name": "c",
                "platform_assignment_id": "1",
                "title": "t",
            },
        )
        assert resp.status_code == 400

    def test_list_after_import(self, client, auth_headers):
        client.post(
            "/api/assignments/import",
            headers=auth_headers,
            json={
                "platform_id": "educoder",
                "platform_course_id": "42",
                "course_name": "测试课程",
                "platform_assignment_id": "hw2",
                "title": "第二份作业",
            },
        )
        resp = client.get("/api/assignments", headers=auth_headers)
        assert resp.status_code == 200
        data = resp.json()
        assert len(data) >= 1
        titles = {a["title"] for a in data}
        assert "第二份作业" in titles

    def test_set_completion(self, client, auth_headers):
        resp = client.post(
            "/api/assignments/import",
            headers=auth_headers,
            json={
                "platform_id": "educoder",
                "platform_course_id": "42",
                "course_name": "测试课程",
                "platform_assignment_id": "hw3",
                "title": "第三份作业",
            },
        )
        assignment_id = resp.json()["id"]

        comp = client.post(
            f"/api/assignments/{assignment_id}/completion",
            headers=auth_headers,
            json={"completed": True},
        )
        assert comp.status_code == 200
        assert comp.json()["manual_status"] == "completed"
        assert comp.json()["effective_status"] == "completed"

        un_comp = client.post(
            f"/api/assignments/{assignment_id}/completion",
            headers=auth_headers,
            json={"completed": False},
        )
        assert un_comp.status_code == 200
        assert un_comp.json()["manual_status"] is None

    def test_list_excludes_completed(self, client, auth_headers):
        import_resp = client.post(
            "/api/assignments/import",
            headers=auth_headers,
            json={
                "platform_id": "educoder",
                "platform_course_id": "42",
                "course_name": "c",
                "platform_assignment_id": "hw_done",
                "title": "done",
            },
        )
        assignment_id = import_resp.json()["id"]
        client.post(
            f"/api/assignments/{assignment_id}/completion",
            headers=auth_headers,
            json={"completed": True},
        )
        resp = client.get("/api/assignments", headers=auth_headers)
        titles = {a["title"] for a in resp.json()}
        assert "done" not in titles

    def test_complete_nonexistent(self, client, auth_headers):
        resp = client.post(
            "/api/assignments/99999/completion",
            headers=auth_headers,
            json={"completed": True},
        )
        assert resp.status_code == 404
