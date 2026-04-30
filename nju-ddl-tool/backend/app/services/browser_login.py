from dataclasses import dataclass
import logging
import os
from pathlib import Path
import shutil
import sys
import uuid

from playwright.async_api import BrowserContext, Error as PlaywrightError, Page, async_playwright

from ..config import get_settings
from ..platforms.base import PlatformAdapter

logger = logging.getLogger(__name__)


class BrowserLoginUnavailable(RuntimeError):
    pass


@dataclass
class LoginSession:
    id: str
    user_id: int
    platform_id: str
    adapter: PlatformAdapter
    context: BrowserContext
    page: Page


class BrowserLoginManager:
    def __init__(self) -> None:
        self._playwright = None
        self._sessions: dict[str, LoginSession] = {}

    async def _ensure_playwright(self):
        if self._playwright is None:
            self._playwright = await async_playwright().start()
        return self._playwright

    @staticmethod
    def _has_graphical_display() -> bool:
        if not sys.platform.startswith("linux"):
            return True
        return bool(os.getenv("DISPLAY") or os.getenv("WAYLAND_DISPLAY"))

    @staticmethod
    def _ensure_interactive_browser_available(headless: bool) -> None:
        if headless:
            raise BrowserLoginUnavailable(
                "平台登录需要可见浏览器。当前后端运行在 headless 模式，请在有桌面环境的终端设置 "
                "NJU_DDL_PLAYWRIGHT_HEADLESS=false 后重启，或配置远程可视化。"
            )
        if not BrowserLoginManager._has_graphical_display():
            raise BrowserLoginUnavailable(
                "平台登录需要可见浏览器，但当前服务器没有检测到 DISPLAY/WAYLAND_DISPLAY。"
                "请在有桌面环境的终端运行，或配置 Xvfb/noVNC 等远程可视化后重启。"
            )

    async def start(self, user_id: int, adapter: PlatformAdapter) -> LoginSession:
        settings = get_settings()
        self._ensure_interactive_browser_available(settings.playwright_headless)
        settings.browser_user_data_dir.mkdir(parents=True, exist_ok=True)
        login_id = uuid.uuid4().hex
        user_data_dir = settings.browser_user_data_dir / f"{user_id}-{adapter.id}-{login_id}"
        context: BrowserContext | None = None
        try:
            playwright = await self._ensure_playwright()
            context = await playwright.chromium.launch_persistent_context(
                str(user_data_dir),
                headless=settings.playwright_headless,
            )
            page = context.pages[0] if context.pages else await context.new_page()
            await page.goto(adapter.login_url, wait_until="domcontentloaded")
        except (OSError, PlaywrightError) as exc:
            if context is not None:
                try:
                    await context.close()
                except PlaywrightError:
                    pass
            shutil.rmtree(user_data_dir, ignore_errors=True)
            logger.warning("Browser login startup failed for %s: %s", adapter.id, exc)
            raise BrowserLoginUnavailable(
                "无法启动平台登录浏览器。请确认后端运行环境支持可见浏览器，并已安装 Playwright Chromium。"
            ) from exc
        session = LoginSession(
            id=login_id,
            user_id=user_id,
            platform_id=adapter.id,
            adapter=adapter,
            context=context,
            page=page,
        )
        self._sessions[login_id] = session
        return session

    def get(self, login_id: str) -> LoginSession | None:
        return self._sessions.get(login_id)

    async def check_and_save_state(self, login_id: str) -> tuple[str, str | None, dict | None]:
        session = self._sessions.get(login_id)
        if session is None:
            return "missing", None, None

        current_url = session.page.url
        if await session.adapter.is_logged_in(session.page, navigate=False):
            storage_state = await session.context.storage_state()
            await self.close(login_id, remove_data_dir=False)
            return "complete", current_url, storage_state
        return "pending", current_url, None

    async def close(self, login_id: str, remove_data_dir: bool = True) -> None:
        session = self._sessions.pop(login_id, None)
        if session is None:
            return
        await session.context.close()
        if remove_data_dir:
            base = Path(get_settings().browser_user_data_dir)
            for path in base.glob(f"{session.user_id}-{session.platform_id}-{login_id}"):
                shutil.rmtree(path, ignore_errors=True)

    async def shutdown(self) -> None:
        for login_id in list(self._sessions):
            try:
                await self.close(login_id, remove_data_dir=True)
            except Exception:
                pass
        if self._playwright is not None:
            try:
                await self._playwright.stop()
            except Exception:
                pass
            self._playwright = None


browser_login_manager = BrowserLoginManager()
