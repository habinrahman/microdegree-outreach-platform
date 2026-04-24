"""HR Contact model."""
import uuid
from sqlalchemy import Column, String, DateTime, Boolean
from app.database.config import Base, UuidType
from app.utils.datetime_utils import utc_now


class HRContact(Base):
    __tablename__ = "hr_contacts"

    id = Column(UuidType(), primary_key=True, default=uuid.uuid4)
    name = Column(String(255), nullable=False)
    company = Column(String(255), nullable=False)
    email = Column(String(255), unique=True, index=True, nullable=False)
    domain = Column(String(100), nullable=True)  # legacy field used by existing dashboard
    linkedin_url = Column(String(512), nullable=True)
    designation = Column(String(255), nullable=True)
    city = Column(String(255), nullable=True)
    source = Column(String(255), nullable=True)
    status = Column(String(50), default="active")  # active | responded | invalid | no_response | blacklisted | paused
    # Explicit validity for analytics / filtering (synced with status=invalid on bounce/block).
    is_valid = Column(Boolean, default=True, nullable=False)
    is_demo = Column(Boolean, default=False)
    # Explicit tag: this row is synthetic fixture data (must never appear in operator UI).
    is_fixture_test_data = Column(Boolean, default=False, nullable=False)
    paused_until = Column(DateTime, nullable=True)  # if paused, don't email until this date
    ignored_by_students_count = Column(String(10), nullable=True)  # legacy placeholder; use analytics to compute
    last_contacted_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=utc_now)
