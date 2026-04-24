"""HR ignore actions: a student can mark an HR as ignored."""
import uuid
from sqlalchemy import Column, DateTime, UniqueConstraint, ForeignKey

from app.database.config import Base, UuidType
from app.utils.datetime_utils import utc_now


class HRIgnored(Base):
    __tablename__ = "hr_ignores"
    __table_args__ = (
        UniqueConstraint("student_id", "hr_id", name="uq_hr_ignores_student_hr"),
    )

    id = Column(UuidType(), primary_key=True, default=uuid.uuid4)
    student_id = Column(UuidType(), ForeignKey("students.id"), nullable=False)
    hr_id = Column(UuidType(), ForeignKey("hr_contacts.id"), nullable=False)
    created_at = Column(DateTime, default=utc_now)

