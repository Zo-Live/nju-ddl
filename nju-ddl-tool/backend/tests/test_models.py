import pytest

from app.platforms.base import NormalizedAssignment


class TestNormalizedAssignment:
    def test_valid_status(self):
        for s in ("not_started", "submitted", "completed", "unknown"):
            a = NormalizedAssignment(
                platform_id="test", platform_course_id="1", course_name="c",
                platform_assignment_id="1", title="hw", remote_status=s,
            )
            assert a.remote_status == s

    def test_invalid_status(self):
        with pytest.raises(ValueError):
            NormalizedAssignment(
                platform_id="test", platform_course_id="1", course_name="c",
                platform_assignment_id="1", title="hw", remote_status="bad",
            )

    def test_nullable_fields(self):
        a = NormalizedAssignment(
            platform_id="test", platform_course_id="1", course_name="c",
            platform_assignment_id="1", title="hw",
        )
        assert a.description is None
        assert a.deadline is None
        assert a.published_at is None
        assert a.source_url is None
        assert a.remote_status == "unknown"
