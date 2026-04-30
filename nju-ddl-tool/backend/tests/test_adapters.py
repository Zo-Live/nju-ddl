import inspect
import json
from datetime import datetime, timezone, timedelta

import pytest

from app.platforms.educoder import (
    EducoderAdapter,
    HOMEWORK_TARGETS as EDUCORDER_HOMEWORK_TARGETS,
)
from app.platforms.cslab_cms import (
    CslabCmsAdapter,
    HOMEWORK_TARGETS as CSLAB_HOMEWORK_TARGETS,
)
from app.platforms.nju_lms import (
    HOME_TARGET as LMS_HOME_TARGET,
    HOMEWORK_TARGETS as LMS_HOMEWORK_TARGETS,
    NjuLmsAdapter,
)

EDUCODER_TZ = timezone(timedelta(hours=8))


class FakeResponse:
    def __init__(self, url: str, payload: dict | list, status: int = 200) -> None:
        self.url = url
        self.status = status
        self.payload = payload

    async def text(self):
        return json.dumps(self.payload)


class FakePage:
    def __init__(
        self,
        responses_by_url: dict[str, list[FakeResponse]] | None = None,
        fetch_json: dict[str, dict | list | None] | None = None,
        content: str = "我的课堂 作业 课程",
    ) -> None:
        self.responses_by_url = responses_by_url or {}
        self.fetch_json = fetch_json or {}
        self.content_text = content
        self.goto_urls: list[str] = []
        self.listeners: list = []
        self.url = "about:blank"

    def on(self, event: str, callback):
        assert event == "response"
        self.listeners.append(callback)

    def remove_listener(self, event: str, callback):
        assert event == "response"
        self.listeners.remove(callback)

    async def goto(self, url: str, **_kwargs):
        self.url = url
        self.goto_urls.append(url)
        for response in self.responses_by_url.get(url, []):
            for listener in list(self.listeners):
                result = listener(response)
                if inspect.isawaitable(result):
                    await result

    async def wait_for_timeout(self, _ms: int):
        return None

    async def content(self):
        return self.content_text

    async def evaluate(self, _script, args=None):
        if isinstance(args, list) and args:
            return self.fetch_json.get(args[0])
        return None


class FakeContext:
    def __init__(self, page: FakePage) -> None:
        self.page = page

    async def new_page(self):
        return self.page


class FakeBrowser:
    def __init__(self, page: FakePage) -> None:
        self.page = page
        self.closed = False

    async def new_context(self, **_kwargs):
        return FakeContext(self.page)

    async def close(self):
        self.closed = True


class FakeChromium:
    def __init__(self, page: FakePage) -> None:
        self.page = page

    async def launch(self, **_kwargs):
        return FakeBrowser(self.page)


class FakePlaywright:
    def __init__(self, page: FakePage) -> None:
        self.chromium = FakeChromium(page)


class FakeAsyncPlaywright:
    def __init__(self, page: FakePage) -> None:
        self.page = page

    async def __aenter__(self):
        return FakePlaywright(self.page)

    async def __aexit__(self, *_args):
        return None


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


class TestFixedHomeworkTargets:
    def test_educoder_targets_are_limited_to_required_pages(self):
        assert [target.url for target in EDUCORDER_HOMEWORK_TARGETS] == [
            "https://www.educoder.net/classrooms/WUYO52NE/shixun_homework",
            "https://www.educoder.net/classrooms/8pyfozik/group_homework",
        ]

    def test_cslab_targets_are_limited_to_required_pages(self):
        assert [target.url for target in CSLAB_HOMEWORK_TARGETS] == [
            "https://cslab-cms.nju.edu.cn/classrooms/2tve6rzi/shixun_homework",
            "https://cslab-cms.nju.edu.cn/classrooms/2tve6rzi/common_homework",
            "https://cslab-cms.nju.edu.cn/classrooms/z3gx5tby/common_homework",
        ]

    def test_lms_targets_are_limited_to_home_and_required_courses(self):
        assert LMS_HOME_TARGET.url == "https://lms.nju.edu.cn/"
        assert [target.url for target in LMS_HOMEWORK_TARGETS] == [
            "https://lms.nju.edu.cn/course/6165/homework#/?pageIndex=1",
            "https://lms.nju.edu.cn/course/6106/homework#/?pageIndex=1",
        ]

    @pytest.mark.asyncio
    async def test_educoder_collects_only_target_page_homeworks(self):
        target = EDUCORDER_HOMEWORK_TARGETS[0]
        page = FakePage({
            target.url: [
                FakeResponse(
                    "https://data.educoder.net/api/courses/WUYO52NE/homework_commons.json",
                    {
                        "homeworks": [
                            {
                                "homework_id": 101,
                                "name": "实验一",
                                "end_time": "2026-04-30 23:55",
                                "un_commit_work": True,
                                "course_name": "目标课堂",
                            }
                        ]
                    },
                )
            ]
        })

        items = await EducoderAdapter()._fetch_target_assignments(page, target)

        assert page.goto_urls == [target.url]
        assert items[0].platform_course_id == "WUYO52NE"
        assert items[0].course_name == "目标课堂"
        assert items[0].platform_assignment_id == "101"
        assert items[0].source_url == (
            "https://www.educoder.net/classrooms/WUYO52NE/shixun_homework/101/detail"
        )

    @pytest.mark.asyncio
    async def test_cslab_refresh_does_not_require_localstorage_login(self, monkeypatch):
        page = FakePage(content="作业 课程")

        async def fail_if_called(_self, _page):
            raise AssertionError("_get_zzud should not be used during CSLab refresh")

        monkeypatch.setattr(CslabCmsAdapter, "_get_zzud", fail_if_called)
        monkeypatch.setattr(
            "app.platforms.cslab_cms.async_playwright",
            lambda: FakeAsyncPlaywright(page),
        )

        items = await CslabCmsAdapter().fetch_assignments({"cookies": []})

        assert items == []
        assert page.goto_urls == [
            "https://cslab-cms.nju.edu.cn/",
            "https://cslab-cms.nju.edu.cn/classrooms/2tve6rzi/shixun_homework",
            "https://cslab-cms.nju.edu.cn/classrooms/2tve6rzi/common_homework",
            "https://cslab-cms.nju.edu.cn/classrooms/z3gx5tby/common_homework",
        ]

    @pytest.mark.asyncio
    async def test_lms_empty_homework_pages_return_empty_list(self, monkeypatch):
        page = FakePage(
            fetch_json={
                "https://lms.nju.edu.cn/api/courses/6165/homework-activities": {
                    "homework_activities": []
                },
                "https://lms.nju.edu.cn/api/courses/6106/homework-activities": {
                    "homework_activities": []
                },
            }
        )
        monkeypatch.setattr(
            "app.platforms.nju_lms.async_playwright",
            lambda: FakeAsyncPlaywright(page),
        )

        items = await NjuLmsAdapter().fetch_assignments({"cookies": []})

        assert items == []
        assert page.goto_urls == [
            "https://lms.nju.edu.cn/",
            "https://lms.nju.edu.cn/",
            "https://lms.nju.edu.cn/course/6165/homework#/?pageIndex=1",
            "https://lms.nju.edu.cn/course/6106/homework#/?pageIndex=1",
        ]

    @pytest.mark.asyncio
    async def test_lms_collects_homepage_and_course_homeworks(self):
        home = LMS_HOME_TARGET
        course = LMS_HOMEWORK_TARGETS[0]
        page = FakePage({
            home.url: [
                FakeResponse(
                    "https://lms.nju.edu.cn/api/todo/homework",
                    {
                        "todos": [
                            {
                                "id": 1,
                                "title": "主页待办",
                                "course_id": 6165,
                                "course_name": "课程 A",
                                "deadline": "2026-03-20T15:59:00Z",
                            }
                        ]
                    },
                )
            ],
            course.url: [
                FakeResponse(
                    "https://lms.nju.edu.cn/api/courses/6165/homework-activities",
                    {
                        "homework_activities": [
                            {
                                "id": 2,
                                "title": "课程作业",
                                "deadline": "2026-03-21T15:59:00Z",
                            }
                        ]
                    },
                )
            ],
        })

        home_items = await NjuLmsAdapter()._fetch_target_assignments(page, home)
        course_items = await NjuLmsAdapter()._fetch_target_assignments(page, course)

        assert [item.title for item in home_items + course_items] == ["主页待办", "课程作业"]
        assert course_items[0].platform_course_id == "6165"
