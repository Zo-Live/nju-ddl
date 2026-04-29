from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import Assignment, Course
from ..platforms.base import NormalizedAssignment
from ..schemas import AssignmentImport


def effective_status(assignment: Assignment) -> str:
    return assignment.manual_status or assignment.remote_status or "unknown"


def upsert_course(
    db: Session,
    user_id: int,
    platform_id: str,
    platform_course_id: str,
    course_name: str,
    source_url: str | None = None,
) -> Course:
    course = db.scalar(
        select(Course).where(
            Course.user_id == user_id,
            Course.platform_id == platform_id,
            Course.platform_course_id == platform_course_id,
        )
    )
    if course is None:
        course = Course(
            user_id=user_id,
            platform_id=platform_id,
            platform_course_id=platform_course_id,
            name=course_name,
            source_url=source_url,
        )
        db.add(course)
    else:
        course.name = course_name
        course.source_url = source_url or course.source_url
        course.last_seen_at = datetime.now(timezone.utc)
    return course


def upsert_assignment(db: Session, user_id: int, item: NormalizedAssignment | AssignmentImport) -> Assignment:
    now = datetime.now(timezone.utc)
    upsert_course(
        db,
        user_id=user_id,
        platform_id=item.platform_id,
        platform_course_id=item.platform_course_id,
        course_name=item.course_name,
        source_url=item.source_url,
    )
    assignment = db.scalar(
        select(Assignment).where(
            Assignment.user_id == user_id,
            Assignment.platform_id == item.platform_id,
            Assignment.platform_assignment_id == item.platform_assignment_id,
        )
    )
    if assignment is None:
        assignment = Assignment(
            user_id=user_id,
            platform_id=item.platform_id,
            platform_course_id=item.platform_course_id,
            course_name=item.course_name,
            platform_assignment_id=item.platform_assignment_id,
            title=item.title,
        )
        db.add(assignment)

    assignment.platform_course_id = item.platform_course_id
    assignment.course_name = item.course_name
    assignment.title = item.title
    assignment.description = item.description
    assignment.deadline = item.deadline
    assignment.published_at = item.published_at
    assignment.remote_status = item.remote_status
    assignment.source_url = item.source_url
    assignment.last_seen_at = now
    return assignment
