from .base import PlatformAdapter
from .cslab_cms import CslabCmsAdapter
from .educoder import EducoderAdapter
from .nju_lms import NjuLmsAdapter


ADAPTERS: dict[str, PlatformAdapter] = {
    adapter.id: adapter
    for adapter in (
        EducoderAdapter(),
        NjuLmsAdapter(),
        CslabCmsAdapter(),
    )
}


def get_adapter(platform_id: str) -> PlatformAdapter:
    try:
        return ADAPTERS[platform_id]
    except KeyError as exc:
        raise ValueError(f"Unknown platform: {platform_id}") from exc
