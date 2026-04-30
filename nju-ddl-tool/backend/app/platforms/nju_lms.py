import json
import logging
from datetime import datetime, timezone, timedelta

from playwright.async_api import async_playwright

from ..config import get_settings
from .base import NormalizedAssignment, PlatformAdapter, PlatformFetchError

logger = logging.getLogger(__name__)

PAGE_BASE = "https://lms.nju.edu.cn"
API_BASE = f"{PAGE_BASE}/api"


class NjuLmsAdapter(PlatformAdapter):
    id = "nju_lms"
    name = "NJU LMS"
    login_url = PAGE_BASE + "/"

    async def is_logged_in(self, page) -> bool:
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

                courses = await self._fetch_json(page, f"{API_BASE}/my-courses", method="POST", body={})
                if not courses:
                    return []

                course_list = courses.get("courses", [])
                results: list[NormalizedAssignment] = []
                for c in course_list:
                    items = await self._get_homework(page, c)
                    results.extend(items)

                return results
            finally:
                await browser.close()

    # ------------------------------------------------------------------
    # API helpers
    # ------------------------------------------------------------------

    async def _fetch_json(self, page, url: str, method="GET", body=None):
        try:
            result = await page.evaluate(
                """
                async ([url, method, body]) => {
                    const opts = { method, headers: { 'Content-Type': 'application/json' } };
                    if (body !== null && body !== undefined) opts.body = body;
                    const r = await fetch(url, opts);
                    if (!r.ok) return null;
                    return await r.json();
                }
                """,
                [url, method, json.dumps(body) if body is not None else None],
            )
            return result
        except Exception:
            return None

    async def _get_homework(self, page, course: dict) -> list[NormalizedAssignment]:
        course_id = course["id"]
        course_name = course.get("display_name") or course.get("name", "")

        data = await self._fetch_json(page, f"{API_BASE}/courses/{course_id}/homework-activities")
        if not data:
            return []

        activities = data.get("homework_activities", [])
        results: list[NormalizedAssignment] = []
        for hw in activities:
            if not hw.get("published"):
                continue
            results.append(self._normalize(hw, course_id, course_name))
        return results

    # ------------------------------------------------------------------
    # Normalization
    # ------------------------------------------------------------------

    def _normalize(self, hw: dict, course_id: int, course_name: str) -> NormalizedAssignment:
        return NormalizedAssignment(
            platform_id=self.id,
            platform_course_id=str(course_id),
            course_name=course_name,
            platform_assignment_id=str(hw["id"]),
            title=hw.get("title", ""),
            description=self._html_to_text(hw.get("data", {}).get("description")),
            deadline=self._parse_iso(hw.get("deadline") or hw.get("end_time")),
            published_at=self._parse_iso(
                (hw.get("data") or {}).get("publish_time") or hw.get("created_at")
            ),
            remote_status=self._map_status(hw),
            source_url=(
                f"{PAGE_BASE}/course/{course_id}/learning-activity#/{hw['id']}"
            ),
        )

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
