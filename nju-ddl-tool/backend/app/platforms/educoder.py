from .base import NormalizedAssignment, PlatformAdapter, PlatformFetchError


class EducoderAdapter(PlatformAdapter):
    id = "educoder"
    name = "Educoder"
    login_url = "https://www.educoder.net/"

    async def is_logged_in(self, page) -> bool:
        await page.goto(self.login_url, wait_until="domcontentloaded")
        content = await page.content()
        return "退出" in content or "我的课堂" in content or "个人中心" in content

    async def fetch_assignments(self, storage_state: dict) -> list[NormalizedAssignment]:
        raise PlatformFetchError(
            "Educoder assignment extraction is not mapped yet. "
            "Inspect authenticated network requests and implement this adapter."
        )
