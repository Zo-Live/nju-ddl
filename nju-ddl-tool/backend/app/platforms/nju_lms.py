import json
import logging
from dataclasses import dataclass
from datetime import datetime, timezone, timedelta

from playwright.async_api import async_playwright

from ..config import get_settings
from .base import NormalizedAssignment, PlatformAdapter, PlatformFetchError

logger = logging.getLogger(__name__)

PAGE_BASE = "https://lms.nju.edu.cn"
API_BASE = f"{PAGE_BASE}/api"


@dataclass(frozen=True)
class LmsHomeworkTarget:
    course_id: int | None
    course_name: str
    url: str


HOME_TARGET = LmsHomeworkTarget(
    course_id=None,
    course_name="NJU LMS",
    url=PAGE_BASE + "/",
)

HOMEWORK_TARGETS = (
    LmsHomeworkTarget(
        course_id=6165,
        course_name="6165",
        url=f"{PAGE_BASE}/course/6165/homework#/?pageIndex=1",
    ),
    LmsHomeworkTarget(
        course_id=6106,
        course_name="6106",
        url=f"{PAGE_BASE}/course/6106/homework#/?pageIndex=1",
    ),
)

HOMEWORK_RESPONSE_TOKENS = (
    "homework",
    "todo",
    "to-do",
    "activity",
    "activities",
)


class NjuLmsAdapter(PlatformAdapter):
    id = "nju_lms"
    name = "NJU LMS"
    login_url = PAGE_BASE + "/"

    async def is_logged_in(self, page, *, navigate: bool = True) -> bool:
        if navigate:
            await page.goto(self.login_url, wait_until="domcontentloaded")
        url = page.url.lower()
        if "authserver.nju.edu.cn" in url or "lms-identity" in url:
            return False
        try:
            raw = await page.evaluate("() => localStorage.getItem('userInfo') || localStorage.getItem('user')")
            if raw:
                info = json.loads(raw)
                if info.get("login") or info.get("name"):
                    return True
        except Exception:
            pass
        return "lms.nju.edu.cn" in url and "authserver" not in url

    # ------------------------------------------------------------------
    # Public entry point
    # ------------------------------------------------------------------

    async def fetch_assignments(self, storage_state: dict) -> list[NormalizedAssignment]:
        if not storage_state:
            raise PlatformFetchError("NJU LMS: empty storage_state, user must re-authenticate")

        async with async_playwright() as pw:
            browser = await pw.chromium.launch(headless=get_settings().playwright_headless)
            try:
                context = await browser.new_context(storage_state=storage_state)
                page = await context.new_page()

                if not await self.is_logged_in(page):
                    raise PlatformFetchError("NJU LMS: session expired, user must re-authenticate")

                results: list[NormalizedAssignment] = []
                seen: set[str] = set()
                for target in (HOME_TARGET, *HOMEWORK_TARGETS):
                    for item in await self._fetch_target_assignments(page, target):
                        if item.platform_assignment_id in seen:
                            continue
                        seen.add(item.platform_assignment_id)
                        results.append(item)

                return results
            finally:
                await browser.close()

    # ------------------------------------------------------------------
    # API helpers
    # ------------------------------------------------------------------

    async def _fetch_target_assignments(
        self, page, target: LmsHomeworkTarget
    ) -> list[NormalizedAssignment]:
        captured: list[dict] = []

        async def _on_response(response):
            if response.status != 200:
                return
            if not self._is_homework_response(response.url, target):
                return
            try:
                body = await response.text()
                parsed = json.loads(body)
                captured.extend(self._extract_homeworks(parsed))
            except Exception:
                pass

        page.on("response", _on_response)
        try:
            await page.goto(target.url, wait_until="domcontentloaded", timeout=20000)
            await page.wait_for_timeout(3000)
        except Exception as exc:
            logger.warning("NJU LMS target fetch failed for %s: %s", target.url, exc)
        finally:
            try:
                page.remove_listener("response", _on_response)
            except Exception:
                pass

        if not captured and target.course_id is not None:
            data = await self._fetch_json(
                page, f"{API_BASE}/courses/{target.course_id}/homework-activities"
            )
            captured.extend(self._extract_homeworks(data))

        items: list[NormalizedAssignment] = []
        seen: set[str] = set()
        for hw in captured:
            assignment_id = self._homework_id(hw)
            title = self._homework_title(hw)
            course_id = self._course_id(hw, target)
            if not assignment_id or not title or course_id is None:
                continue
            dedupe_key = f"{course_id}:{assignment_id}"
            if dedupe_key in seen:
                continue
            seen.add(dedupe_key)
            item = self._normalize(hw, course_id, self._course_name(hw, target), target.url)
            if item is not None:
                items.append(item)
        return items

    async def _fetch_json(self, page, url: str, method="GET", body=None):
        try:
            result = await page.evaluate(
                """
                async ([url, method, body]) => {
                    const opts = {
                        method,
                        credentials: 'include',
                        headers: {
                            'Accept': 'application/json',
                            'Content-Type': 'application/json',
                        },
                    };
                    if (body !== null && body !== undefined) opts.body = body;
                    const r = await fetch(url, opts);
                    if (!r.ok) return null;
                    const contentType = r.headers.get('content-type') || '';
                    if (!contentType.includes('application/json')) return null;
                    return await r.json();
                }
                """,
                [url, method, json.dumps(body) if body is not None else None],
            )
            return result
        except Exception:
            return None

    async def _get_homework(self, page, course: dict) -> list[NormalizedAssignment]:
        course_id = course.get("id")
        if course_id is None:
            return []
        course_name = course.get("display_name") or course.get("name", "")

        data = await self._fetch_json(page, f"{API_BASE}/courses/{course_id}/homework-activities")
        if not data:
            return []

        activities = self._extract_homeworks(data)
        results: list[NormalizedAssignment] = []
        for hw in activities:
            if hw.get("published") is False:
                continue
            item = self._normalize(
                hw,
                int(course_id),
                course_name,
                f"{PAGE_BASE}/course/{course_id}/homework#/?pageIndex=1",
            )
            if item is not None:
                results.append(item)
        return results

    # ------------------------------------------------------------------
    # Normalization
    # ------------------------------------------------------------------

    def _normalize(
        self, hw: dict, course_id: int, course_name: str, fallback_source_url: str
    ) -> NormalizedAssignment | None:
        if hw.get("published") is False:
            return None
        assignment_id = self._homework_id(hw)
        title = self._homework_title(hw)
        if assignment_id is None or not title:
            return None
        source_url = hw.get("source_url") or hw.get("url") or hw.get("link") or fallback_source_url
        if not isinstance(source_url, str):
            source_url = fallback_source_url
        if isinstance(source_url, str) and source_url.startswith("/"):
            source_url = PAGE_BASE + source_url
        return NormalizedAssignment(
            platform_id=self.id,
            platform_course_id=str(course_id),
            course_name=course_name,
            platform_assignment_id=str(assignment_id),
            title=title,
            description=self._html_to_text(self._description(hw)),
            deadline=self._parse_iso(hw.get("deadline") or hw.get("end_time")),
            published_at=self._parse_iso(self._published_at(hw)),
            remote_status=self._map_status(hw),
            source_url=source_url,
        )

    @staticmethod
    def _is_homework_response(url: str, target: LmsHomeworkTarget) -> bool:
        lower_url = url.lower()
        if "lms.nju.edu.cn" not in lower_url:
            return False
        if target.course_id is not None and str(target.course_id) not in lower_url:
            return False
        return any(token in lower_url for token in HOMEWORK_RESPONSE_TOKENS)

    @classmethod
    def _extract_homeworks(cls, payload) -> list[dict]:
        found: list[dict] = []

        def collect(value) -> None:
            if isinstance(value, list):
                for item in value:
                    if (
                        isinstance(item, dict)
                        and cls._homework_id(item)
                        and cls._homework_title(item)
                    ):
                        found.append(item)
                    elif isinstance(item, dict):
                        collect(item)
            elif isinstance(value, dict):
                for key in (
                    "homework_activities",
                    "homeworks",
                    "assignments",
                    "todos",
                    "todo_items",
                    "activities",
                    "data",
                    "items",
                    "list",
                    "records",
                    "results",
                ):
                    if key in value:
                        collect(value[key])

        collect(payload)
        return found

    @staticmethod
    def _homework_id(hw: dict):
        return (
            hw.get("id")
            or hw.get("homework_id")
            or hw.get("activity_id")
            or hw.get("homework_activity_id")
        )

    @staticmethod
    def _homework_title(hw: dict) -> str | None:
        value = hw.get("title") or hw.get("name") or hw.get("activity_name")
        return str(value) if value is not None else None

    @staticmethod
    def _course_id(hw: dict, target: LmsHomeworkTarget) -> int | None:
        value = hw.get("course_id") or hw.get("courseId")
        course = hw.get("course")
        if value is None and isinstance(course, dict):
            value = course.get("id")
        if value is None:
            value = target.course_id
        if value is None:
            return None
        try:
            return int(value)
        except (TypeError, ValueError):
            return None

    @staticmethod
    def _course_name(hw: dict, target: LmsHomeworkTarget) -> str:
        course = hw.get("course")
        if isinstance(course, dict):
            value = course.get("display_name") or course.get("name")
            if value:
                return str(value)
        value = hw.get("course_name") or hw.get("courseName")
        return str(value) if value else target.course_name

    @staticmethod
    def _description(hw: dict) -> str | None:
        data = hw.get("data")
        if isinstance(data, dict):
            value = data.get("description")
            if value:
                return str(value)
        value = hw.get("description")
        return str(value) if value else None

    @staticmethod
    def _published_at(hw: dict) -> str | None:
        data = hw.get("data")
        if isinstance(data, dict) and data.get("publish_time"):
            return str(data["publish_time"])
        value = hw.get("created_at") or hw.get("publish_time")
        return str(value) if value else None

    @staticmethod
    def _parse_iso(value: str | None) -> datetime | None:
        if not value:
            return None
        for fmt in ("%Y-%m-%dT%H:%M:%SZ", "%Y-%m-%dT%H:%M:%S%z", "%Y-%m-%dT%H:%M:%S.%f%z"):
            try:
                dt = datetime.strptime(value.strip(), fmt)
                return dt.astimezone(timezone.utc) if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
            except ValueError:
                continue
        return None

    @staticmethod
    def _map_status(hw: dict) -> str:
        if not hw.get("is_closed", False):
            return "not_started"
        return "submitted"

    @staticmethod
    def _html_to_text(html: str | None) -> str | None:
        if not html:
            return None
        import re
        text = re.sub(r"<[^>]+>", "", html)
        return text.strip() or None
