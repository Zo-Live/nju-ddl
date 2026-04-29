from .base import NormalizedAssignment, PlatformAdapter, PlatformFetchError


class CslabCmsAdapter(PlatformAdapter):
    id = "cslab_cms"
    name = "CSLab CMS"
    login_url = "https://cslab-cms.nju.edu.cn/"

    async def is_logged_in(self, page) -> bool:
        await page.goto(self.login_url, wait_until="domcontentloaded")
        url = page.url.lower()
        if "authserver.nju.edu.cn" in url:
            return False
        content = await page.content()
        return "作业" in content or "课程" in content or "cslab-cms.nju.edu.cn" in url

    async def fetch_assignments(self, storage_state: dict) -> list[NormalizedAssignment]:
        raise PlatformFetchError(
            "CSLab CMS assignment extraction is not mapped yet. "
            "Use an authenticated browser trace to locate assignment data."
        )
