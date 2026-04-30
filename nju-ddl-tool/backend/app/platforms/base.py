from dataclasses import dataclass
from datetime import datetime


VALID_STATUSES = {"not_started", "submitted", "completed", "unknown"}


class PlatformFetchError(RuntimeError):
    pass


@dataclass(frozen=True)
class NormalizedAssignment:
    platform_id: str
    platform_course_id: str
    course_name: str
    platform_assignment_id: str
    title: str
    description: str | None = None
    deadline: datetime | None = None
    published_at: datetime | None = None
    remote_status: str = "unknown"
    source_url: str | None = None

    def __post_init__(self) -> None:
        if self.remote_status not in VALID_STATUSES:
            raise ValueError(f"Invalid assignment status: {self.remote_status}")


class PlatformAdapter:
    id: str
    name: str
    login_url: str

    async def is_logged_in(self, page, *, navigate: bool = True) -> bool:
        raise NotImplementedError

    async def fetch_assignments(self, storage_state: dict) -> list[NormalizedAssignment]:
        raise NotImplementedError
