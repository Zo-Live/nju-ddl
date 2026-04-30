from pathlib import Path

import pytest
from playwright.async_api import Error as PlaywrightError

from app.config import get_settings
from app.services import browser_login as browser_login_module
from app.services.browser_login import BrowserLoginManager, BrowserLoginUnavailable


class DummyAdapter:
    id = "dummy"
    login_url = "https://example.com"


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
