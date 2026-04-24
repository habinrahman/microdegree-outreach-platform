"""Per-student daily email send counters (UTC calendar day)."""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from uuid import UUID

from sqlalchemy.orm import Session

from app.models import Student
from app.utils.datetime_utils import utc_now

logger = logging.getLogger(__name__)


def record_student_successful_email(db: Session, student_id: UUID) -> None:
    student = db.query(Student).filter(Student.id == student_id).first()
    if student is None:
        return

    now = datetime.now(timezone.utc)

    if not student.last_sent_at:
        student.emails_sent_today = 0
    else:
        logger.debug("Student usage reset check: %s %s", student.id, student.last_sent_at)
        if student.last_sent_at.tzinfo is None:
            logger.debug("Fixing naive datetime for student: %s", student.id)
            student.last_sent_at = student.last_sent_at.replace(tzinfo=timezone.utc)
        last = student.last_sent_at.astimezone(timezone.utc)
        if last.date() != now.date():
            student.emails_sent_today = 0

    student.emails_sent_today = int(student.emails_sent_today or 0) + 1
    student.last_sent_at = utc_now()
    db.add(student)
