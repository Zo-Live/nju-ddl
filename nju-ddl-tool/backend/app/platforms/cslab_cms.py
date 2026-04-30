import json
import logging
from dataclasses import dataclass
from datetime import datetime, timezone, timedelta
from urllib.parse import urlencode

from playwright.async_api import async_playwright

from ..config import get_settings
from .base import NormalizedAssignment, PlatformAdapter, PlatformFetchError

logger = logging.getLogger(__name__)

EDUCODER_TZ = timezone(timedelta(hours=8))
PAGE_BASE = "https://cslab-cms.nju.edu.cn"
API_BASE = f"{PAGE_BASE}/api"


@dataclass(frozen=True)
class HomeworkTarget:
    classroom_id: str
    tab: str
    course_name: str
    url: str


HOMEWORK_TARGETS = (
    HomeworkTarget(
        classroom_id="2tve6rzi",
        tab="shixun_homework",
        course_name="2tve6rzi",
        url=f"{PAGE_BASE}/classrooms/2tve6rzi/shixun_homework",
    ),
    HomeworkTarget(
        classroom_id="2tve6rzi",
        tab="common_homework",
        course_name="2tve6rzi",
        url=f"{PAGE_BASE}/classrooms/2tve6rzi/common_homework",
    ),
    HomeworkTarget(
        classroom_id="z3gx5tby",
        tab="common_homework",
        course_name="z3gx5tby",
        url=f"{PAGE_BASE}/classrooms/z3gx5tby/common_homework",
    ),
)

HOMEWORK_RESPONSE_TOKENS = (
    "homework",
    "shixun_homework",
    "common_homework",
)

HOMEWORK_TYPE_BY_TAB = {
    "common_homework": 1,
    "group_homework": 3,
    "shixun_homework": 4,
}


class CslabCmsAdapter(PlatformAdapter):
    id = "cslab_cms"
    name = "CSLab CMS"
    login_url = PAGE_BASE + "/"

    async def is_logged_in(self, page, *, navigate: bool = True) -> bool:
        if navigate:
            await page.goto(self.login_url, wait_until="domcontentloaded")
        url = page.url.lower()
        if "authserver.nju.edu.cn" in url:
            return False
        info = await self._current_user_info(page)
        if info is not None:
            return self._is_real_user(info)
        return False

    async def _current_user_info(self, page) -> dict | None:
        try:
            raw = await page.evaluate("() => localStorage.getItem('userInfo')")
            if raw:
                info = json.loads(raw)
                if isinstance(info, dict):
                    return info
        except Exception:
            pass

        data = await self._fetch_json(page, f"{API_BASE}/users/get_user_info.json")
        return data if isinstance(data, dict) else None

    @staticmethod
    def _is_real_user(info: dict | None) -> bool:
        if not info:
            return False
        return bool(info.get("login")) and info.get("real_name") != "游客"

    # ------------------------------------------------------------------
    # Public entry point
    # ------------------------------------------------------------------

    async def fetch_assignments(self, storage_state: dict) -> list[NormalizedAssignment]:
        if not storage_state:
            raise PlatformFetchError("CSLab CMS: empty storage_state, user must re-authenticate")

        async with async_playwright() as pw:
            browser = await pw.chromium.launch(headless=get_settings().playwright_headless)
            try:
                context = await browser.new_context(storage_state=storage_state)
                page = await context.new_page()

                if not await self.is_logged_in(page):
                    raise PlatformFetchError("CSLab CMS: session expired, user must re-authenticate")

                results: list[NormalizedAssignment] = []
                seen: set[str] = set()
                for target in HOMEWORK_TARGETS:
                    for item in await self._fetch_target_assignments(page, target):
                        if item.platform_assignment_id in seen:
                            continue
                        seen.add(item.platform_assignment_id)
                        results.append(item)

                return results
            finally:
                await browser.close()

    # ------------------------------------------------------------------
    # Homework extraction
    # ------------------------------------------------------------------

    async def _get_zzud(self, page) -> str | None:
        try:
            raw = await page.evaluate("() => localStorage.getItem('userInfo')")
            if raw:
                return json.loads(raw).get("login")
        except Exception:
            pass
        return None

    async def _fetch_target_assignments(
        self, page, target: HomeworkTarget
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
            logger.warning("CSLab CMS target fetch failed for %s: %s", target.url, exc)
        finally:
            try:
                page.remove_listener("response", _on_response)
            except Exception:
                pass

        if not captured:
            captured.extend(await self._fetch_target_json_fallback(page, target))

        items: list[NormalizedAssignment] = []
        seen: set[str] = set()
        for hw in captured:
            assignment_id = self._homework_id(hw)
            title = self._homework_title(hw)
            if not assignment_id or not title or assignment_id in seen:
                continue
            seen.add(assignment_id)
            try:
                items.append(self._normalize(hw, target))
            except Exception as exc:
                logger.warning("CSLab CMS assignment normalization failed for %s: %s", assignment_id, exc)
        return items

    async def _fetch_target_json_fallback(self, page, target: HomeworkTarget) -> list[dict]:
        homework_type = HOMEWORK_TYPE_BY_TAB.get(target.tab)
        params = {
            "type": homework_type,
            "page": 1,
            "limit": 200,
            "status": 0,
        }
        candidates = [
            f"{API_BASE}/courses/{target.classroom_id}/homework_commons.json?{urlencode(params)}",
            f"{API_BASE}/courses/{target.classroom_id}/homework_commons/list.json?{urlencode(params)}",
            f"{API_BASE}/courses/{target.classroom_id}/homework_commons.json",
            f"{API_BASE}/courses/{target.classroom_id}/homework_commons/list.json",
        ]

        found: list[dict] = []
        for url in candidates:
            data = await self._fetch_json(page, url)
            if data:
                found.extend(self._extract_homeworks(data))
            if found:
                break
        return found

    async def _fetch_json(self, page, url: str):
        try:
            return await page.evaluate(
                """
                async ([url]) => {
                    const opts = {
                        method: 'GET',
                        credentials: 'include',
                        headers: {
                            'Accept': 'application/json',
                        },
                    };
                    const r = await fetch(url, opts);
                    if (!r.ok) return null;
                    const contentType = r.headers.get('content-type') || '';
                    if (!contentType.includes('application/json')) return null;
                    return await r.json();
                }
                """,
                [url],
            )
        except Exception as exc:
            logger.warning("CSLab CMS JSON fallback failed for %s: %s", url, exc)
            return None

    @staticmethod
    def _is_homework_response(url: str, target: HomeworkTarget) -> bool:
        lower_url = url.lower()
        if target.classroom_id.lower() not in lower_url:
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
            elif isinstance(value, dict):
                for key in (
                    "homeworks",
                    "homework_commons",
                    "shixun_homeworks",
                    "group_homeworks",
                    "data",
                    "items",
                    "list",
                ):
                    if key in value:
                        collect(value[key])

        collect(payload)
        return found

    # ------------------------------------------------------------------
    # Normalization
    # ------------------------------------------------------------------

    def _normalize(self, hw: dict, target: HomeworkTarget) -> NormalizedAssignment:
        assignment_id = self._homework_id(hw)
        title = self._homework_title(hw)
        course_name = self._homework_course_name(hw) or target.course_name
        return NormalizedAssignment(
            platform_id=self.id,
            platform_course_id=target.classroom_id,
            course_name=course_name,
            platform_assignment_id=str(assignment_id),
            title=title or "",
            description=None,
            deadline=self._parse_datetime(hw.get("end_time_s") or hw.get("end_time")),
            published_at=self._parse_datetime(hw.get("publish_time")),
            remote_status=self._map_status(hw),
            source_url=(
                f"{PAGE_BASE}/classrooms/{target.classroom_id}"
                f"/{target.tab}/{assignment_id}/detail"
            ),
        )

    @staticmethod
    def _homework_id(hw: dict):
        return hw.get("homework_id") or hw.get("homework_common_id") or hw.get("id")

    @staticmethod
    def _homework_title(hw: dict) -> str | None:
        value = hw.get("name") or hw.get("title") or hw.get("homework_name")
        return str(value) if value is not None else None

    @staticmethod
    def _homework_course_name(hw: dict) -> str | None:
        course = hw.get("course")
        if isinstance(course, dict):
            value = course.get("name") or course.get("course_name")
            return str(value) if value is not None else None
        value = hw.get("course_name") or hw.get("course")
        return str(value) if value is not None else None

    @staticmethod
    def _parse_datetime(value: object | None) -> datetime | None:
        if not value:
            return None
        if isinstance(value, datetime):
            return value if value.tzinfo else value.replace(tzinfo=EDUCODER_TZ)
        if isinstance(value, (int, float)):
            timestamp = float(value)
            if timestamp > 10_000_000_000:
                timestamp = timestamp / 1000
            return datetime.fromtimestamp(timestamp, tz=EDUCODER_TZ)
        if not isinstance(value, str):
            return None
        text = value.strip()
        if text.isdigit():
            return CslabCmsAdapter._parse_datetime(int(text))
        for fmt in (
            "%Y-%m-%d %H:%M:%S",
            "%Y-%m-%d %H:%M",
            "%Y-%m-%dT%H:%M:%S%z",
            "%Y-%m-%dT%H:%M:%SZ",
        ):
            try:
                dt = datetime.strptime(text, fmt)
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
