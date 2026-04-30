import json
import logging
from datetime import datetime, timezone, timedelta

from playwright.async_api import async_playwright

from ..config import get_settings
from .base import NormalizedAssignment, PlatformAdapter, PlatformFetchError

logger = logging.getLogger(__name__)

EDUCODER_TZ = timezone(timedelta(hours=8))
PAGE_BASE = "https://www.educoder.net"
API_BASE = "https://data.educoder.net/api"

# (URL tab name, description)
HOMEWORK_TABS = [
    ("shixun_homework", "课堂实验"),
    ("common_homework", "图文作业"),
    ("group_homework", "分组作业"),
    ("program_homework", "编程作业"),
    ("exam", "在线考试"),
    ("poll", "问卷调查"),
]


class EducoderAdapter(PlatformAdapter):
    id = "educoder"
    name = "Educoder"
    login_url = PAGE_BASE + "/"

    async def is_logged_in(self, page, *, navigate: bool = True) -> bool:
        if navigate:
            await page.goto(self.login_url, wait_until="domcontentloaded")
        content = await page.content()
        if "退出" in content or "我的课堂" in content or "个人中心" in content:
            return True
        try:
            raw = await page.evaluate("() => localStorage.getItem('userInfo')")
            if raw:
                info = json.loads(raw)
                if info.get("login"):
                    return True
        except Exception:
            pass
        return False

    # ------------------------------------------------------------------
    # Public entry point
    # ------------------------------------------------------------------

    async def fetch_assignments(self, storage_state: dict) -> list[NormalizedAssignment]:
        if not storage_state:
            raise PlatformFetchError("Educoder: empty storage_state, user must re-authenticate")

        async with async_playwright() as pw:
            browser = await pw.chromium.launch(headless=get_settings().playwright_headless)
            try:
                context = await browser.new_context(storage_state=storage_state)
                page = await context.new_page()

                if not await self.is_logged_in(page):
                    raise PlatformFetchError("Educoder: session expired, user must re-authenticate")

                zzud = await self._get_zzud(page)
                if not zzud:
                    raise PlatformFetchError("Educoder: unable to determine user identity from session")

                courses = await self._fetch_courses_via_navigation(page, zzud)
                if not courses:
                    return []

                results: list[NormalizedAssignment] = []
                for course in courses:
                    items = await self._fetch_course_assignments(page, zzud, course)
                    results.extend(items)

                return results
            finally:
                await browser.close()

    # ------------------------------------------------------------------
    # Session helpers
    # ------------------------------------------------------------------

    async def _get_zzud(self, page) -> str | None:
        try:
            raw = await page.evaluate("() => localStorage.getItem('userInfo')")
            if raw:
                return json.loads(raw).get("login")
        except Exception:
            pass
        return None

    # ------------------------------------------------------------------
    # Step 1 — discover courses by navigating to the classrooms page
    # ------------------------------------------------------------------

    async def _fetch_courses_via_navigation(self, page, zzud: str) -> list[dict]:
        courses_data: dict | None = None

        async def _capture(response):
            nonlocal courses_data
            if courses_data is not None:
                return
            if f"/users/{zzud}/courses.json" not in response.url:
                return
            if response.status != 200:
                return
            try:
                body = await response.text()
                parsed = json.loads(body)
                if parsed.get("courses"):
                    courses_data = parsed
            except Exception:
                pass

        page.on("response", _capture)
        try:
            await page.goto(
                f"{PAGE_BASE}/users/{zzud}/classrooms",
                wait_until="domcontentloaded",
                timeout=30000,
            )
            await page.wait_for_timeout(5000)
        finally:
            page.remove_listener("response", _capture)

        if courses_data is None:
            raise PlatformFetchError("Educoder: failed to fetch course list")
        return courses_data.get("courses", [])

    # ------------------------------------------------------------------
    # Step 2 — navigate each homework tab and collect assignments
    # ------------------------------------------------------------------

    async def _fetch_course_assignments(
        self, page, zzud: str, course: dict
    ) -> list[NormalizedAssignment]:
        course_id = course["id"]
        course_name = course["name"]
        classroom_id = self._classroom_id(course)
        if not classroom_id:
            return []

        all_items: list[dict] = []
        for tab, _tab_name in HOMEWORK_TABS:
            captured: list[dict] = []

            async def _on_response(response):
                if response.status != 200:
                    return
                url = response.url
                if f"/courses/{classroom_id}/" not in url:
                    return
                if "homework_commons" not in url and "polls.json" not in url:
                    return
                try:
                    body = await response.text()
                    parsed = json.loads(body)
                    hws = parsed.get("homeworks") or []
                    if hws:
                        captured.extend(hws)
                except Exception:
                    pass

            page.on("response", _on_response)
            try:
                page_url = f"{PAGE_BASE}/classrooms/{classroom_id}/{tab}"
                await page.goto(page_url, wait_until="domcontentloaded", timeout=20000)
                await page.wait_for_timeout(3000)
            except Exception:
                pass
            finally:
                page.remove_listener("response", _on_response)

            for hw in captured:
                all_items.append(self._normalize(hw, course_id, course_name, classroom_id, tab))

        return all_items

    # ------------------------------------------------------------------
    # Normalization
    # ------------------------------------------------------------------

    def _normalize(
        self, hw: dict, course_id: int, course_name: str, classroom_id: str, tab: str
    ) -> NormalizedAssignment:
        return NormalizedAssignment(
            platform_id=self.id,
            platform_course_id=str(course_id),
            course_name=course_name,
            platform_assignment_id=str(hw["homework_id"]),
            title=hw.get("name", ""),
            description=None,
            deadline=self._parse_datetime(hw.get("end_time_s") or hw.get("end_time")),
            published_at=self._parse_datetime(hw.get("publish_time")),
            remote_status=self._map_status(hw),
            source_url=(
                f"{PAGE_BASE}/classrooms/{classroom_id}"
                f"/{tab}/{hw['homework_id']}/detail"
            ),
        )

    @staticmethod
    def _parse_datetime(value: str | None) -> datetime | None:
        if not value:
            return None
        for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%Y-%m-%dT%H:%M:%S%z"):
            try:
                dt = datetime.strptime(value.strip(), fmt)
                if dt.tzinfo is None:
                    dt = dt.replace(tzinfo=EDUCODER_TZ)
                return dt
            except ValueError:
                continue
        return None

    @staticmethod
    def _map_status(hw: dict) -> str:
        if hw.get("un_commit_work", True):
            return "not_started"
        return "submitted"

    @staticmethod
    def _classroom_id(course: dict) -> str | None:
        url = course.get("first_category_url") or ""
        parts = url.strip("/").split("/")
        if len(parts) >= 2 and parts[0] == "classrooms":
            return parts[1]
        return None
