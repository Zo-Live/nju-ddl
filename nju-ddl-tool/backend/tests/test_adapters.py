from datetime import datetime, timezone, timedelta

from app.platforms.educoder import EducoderAdapter
from app.platforms.cslab_cms import CslabCmsAdapter
from app.platforms.nju_lms import NjuLmsAdapter

EDUCODER_TZ = timezone(timedelta(hours=8))


class TestParseDatetime:
    def test_cst_format(self):
        """Educoder: '2026-04-30 23:55' with seconds variant"""
        for adapter_cls in (EducoderAdapter, CslabCmsAdapter):
            result = adapter_cls._parse_datetime("2026-04-30 23:55")
            assert result == datetime(2026, 4, 30, 23, 55, tzinfo=EDUCODER_TZ)

    def test_cst_with_seconds(self):
        for adapter_cls in (EducoderAdapter, CslabCmsAdapter):
            result = adapter_cls._parse_datetime("2026-04-30 23:55:00")
            assert result == datetime(2026, 4, 30, 23, 55, tzinfo=EDUCODER_TZ)

    def test_iso_utc(self):
        """NJU LMS uses ISO UTC: '2026-03-20T15:59:00Z'"""
        result = NjuLmsAdapter._parse_iso("2026-03-20T15:59:00Z")
        assert result == datetime(2026, 3, 20, 15, 59, tzinfo=timezone.utc)

    def test_iso_with_tz_offset(self):
        for adapter_cls in (CslabCmsAdapter,):
            result = adapter_cls._parse_datetime("2026-04-30T23:55:00+08:00")
            assert result.hour == 23

    def test_none(self):
        for adapter_cls in (EducoderAdapter, CslabCmsAdapter):
            assert adapter_cls._parse_datetime(None) is None
        assert NjuLmsAdapter._parse_iso(None) is None

    def test_invalid(self):
        for adapter_cls in (EducoderAdapter, CslabCmsAdapter):
            assert adapter_cls._parse_datetime("not-a-date") is None

    def test_empty(self):
        assert EducoderAdapter._parse_datetime("") is None


class TestMapStatus:
    def test_not_submitted(self):
        for adapter_cls in (EducoderAdapter, CslabCmsAdapter):
            assert adapter_cls._map_status({"un_commit_work": True}) == "not_started"

    def test_submitted(self):
        for adapter_cls in (EducoderAdapter, CslabCmsAdapter):
            assert adapter_cls._map_status({"un_commit_work": False}) == "submitted"

    def test_default(self):
        """Missing key defaults to True → not_started"""
        assert EducoderAdapter._map_status({}) == "not_started"

    def test_nju_lms_open(self):
        assert NjuLmsAdapter._map_status({"is_closed": False}) == "not_started"

    def test_nju_lms_closed(self):
        assert NjuLmsAdapter._map_status({"is_closed": True}) == "submitted"


class TestClassroomId:
    def test_valid(self):
        assert EducoderAdapter._classroom_id({
            "first_category_url": "/classrooms/abc123/announcement"
        }) == "abc123"

    def test_no_url(self):
        assert EducoderAdapter._classroom_id({}) is None

    def test_empty_url(self):
        assert EducoderAdapter._classroom_id({"first_category_url": ""}) is None

    def test_invalid_url(self):
        assert EducoderAdapter._classroom_id({
            "first_category_url": "/other/abc123"
        }) is None


class TestHtmlToText:
    def test_strips_tags(self):
        result = NjuLmsAdapter._html_to_text("<p>Hello</p><p>World</p>")
        assert result == "HelloWorld"

    def test_none(self):
        assert NjuLmsAdapter._html_to_text(None) is None

    def test_empty(self):
        assert NjuLmsAdapter._html_to_text("") is None
