from dataclasses import dataclass
from pathlib import Path
import shutil
import uuid

from playwright.async_api import BrowserContext, Page, async_playwright

from ..config import get_settings
from ..platforms.base import PlatformAdapter


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

    async def start(self, user_id: int, adapter: PlatformAdapter) -> LoginSession:
        settings = get_settings()
        settings.browser_user_data_dir.mkdir(parents=True, exist_ok=True)
        login_id = uuid.uuid4().hex
        user_data_dir = settings.browser_user_data_dir / f"{user_id}-{adapter.id}-{login_id}"
        playwright = await self._ensure_playwright()
        context = await playwright.chromium.launch_persistent_context(
            str(user_data_dir),
            headless=settings.playwright_headless,
        )
        page = context.pages[0] if context.pages else await context.new_page()
        await page.goto(adapter.login_url, wait_until="domcontentloaded")
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
        if await session.adapter.is_logged_in(session.page):
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


browser_login_manager = BrowserLoginManager()
