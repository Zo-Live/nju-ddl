from pathlib import Path

import pytest
from playwright.async_api import Error as PlaywrightError

from app.config import get_settings
from app.services import browser_login as browser_login_module
from app.services.browser_login import BrowserLoginManager, BrowserLoginUnavailable, LoginSession


class DummyAdapter:
    id = "dummy"
    login_url = "https://example.com"


class FakeContext:
    def __init__(self) -> None:
        self.closed = False

    async def storage_state(self):
        return {"cookies": []}

    async def close(self):
        self.closed = True


class FakePage:
    url = "https://example.com/login"


class TestBrowserLoginAvailability:
    def test_headless_mode_is_unavailable_for_manual_login(self):
        with pytest.raises(BrowserLoginUnavailable, match="headless"):
            BrowserLoginManager._ensure_interactive_browser_available(True)

    def test_linux_without_display_is_unavailable(self, monkeypatch):
        monkeypatch.setattr(browser_login_module.sys, "platform", "linux")
        monkeypatch.delenv("DISPLAY", raising=False)
        monkeypatch.delenv("WAYLAND_DISPLAY", raising=False)

        with pytest.raises(BrowserLoginUnavailable, match="DISPLAY"):
            BrowserLoginManager._ensure_interactive_browser_available(False)

    def test_linux_with_display_allows_manual_login(self, monkeypatch):
        monkeypatch.setattr(browser_login_module.sys, "platform", "linux")
        monkeypatch.setenv("DISPLAY", ":0")
        monkeypatch.delenv("WAYLAND_DISPLAY", raising=False)

        BrowserLoginManager._ensure_interactive_browser_available(False)


class TestBrowserLoginStartupFailure:
    @pytest.mark.asyncio
    async def test_launch_failure_cleans_user_data_dir(self, monkeypatch, tmp_path):
        class FakeChromium:
            async def launch_persistent_context(self, user_data_dir, **_kwargs):
                Path(user_data_dir).mkdir(parents=True, exist_ok=True)
                raise PlaywrightError("boom")

        class FakePlaywright:
            chromium = FakeChromium()

        manager = BrowserLoginManager()
        settings = get_settings()
        monkeypatch.setattr(settings, "browser_user_data_dir", tmp_path)
        monkeypatch.setattr(settings, "playwright_headless", False)
        monkeypatch.setattr(manager, "_ensure_interactive_browser_available", lambda _headless: None)

        async def fake_ensure_playwright():
            return FakePlaywright()

        monkeypatch.setattr(manager, "_ensure_playwright", fake_ensure_playwright)

        with pytest.raises(BrowserLoginUnavailable, match="无法启动平台登录浏览器"):
            await manager.start(1, DummyAdapter())

        assert list(tmp_path.iterdir()) == []


class TestBrowserLoginStatusPolling:
    @pytest.mark.asyncio
    async def test_status_check_does_not_navigate_manual_login_page(self):
        class FakeAdapter(DummyAdapter):
            def __init__(self) -> None:
                self.navigate_values: list[bool] = []

            async def is_logged_in(self, _page, *, navigate: bool = True) -> bool:
                self.navigate_values.append(navigate)
                return True

        manager = BrowserLoginManager()
        adapter = FakeAdapter()
        context = FakeContext()
        manager._sessions["login-id"] = LoginSession(
            id="login-id",
            user_id=1,
            platform_id=adapter.id,
            adapter=adapter,
            context=context,
            page=FakePage(),
        )

        state, current_url, storage_state = await manager.check_and_save_state("login-id")

        assert state == "complete"
        assert current_url == "https://example.com/login"
        assert storage_state == {"cookies": []}
        assert adapter.navigate_values == [False]
        assert context.closed is True
