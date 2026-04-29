from .base import NormalizedAssignment, PlatformAdapter, PlatformFetchError


class NjuLmsAdapter(PlatformAdapter):
    id = "nju_lms"
    name = "NJU LMS"
    login_url = "https://lms.nju.edu.cn/"

    async def is_logged_in(self, page) -> bool:
        await page.goto(self.login_url, wait_until="domcontentloaded")
        url = page.url.lower()
        if "authserver.nju.edu.cn" in url:
            return False
        content = await page.content()
        return "课程" in content or "dashboard" in url or "lms.nju.edu.cn" in url

    async def fetch_assignments(self, storage_state: dict) -> list[NormalizedAssignment]:
        raise PlatformFetchError(
            "NJU LMS assignment extraction is not mapped yet. "
            "Use an authenticated browser trace to locate the assignment API or page."
        )
