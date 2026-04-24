"""Student model."""
import uuid
from sqlalchemy import Column, String, Integer, Boolean, DateTime, Text
from app.database.config import Base, UuidType
from app.utils.datetime_utils import utc_now


class Student(Base):
    __tablename__ = "students"

    id = Column(UuidType(), primary_key=True, default=uuid.uuid4)
    name = Column(String(255), nullable=False)
    gmail_address = Column(String(255), nullable=False)
    experience_years = Column(Integer, default=0)
    skills = Column(Text, nullable=True)
    resume_drive_file_id = Column(String(512), nullable=True)
    resume_file_name = Column(String(255), nullable=True)
    resume_path = Column(String(512), nullable=True)  # local file path for email attachment
    app_password = Column(String(255), nullable=True)  # Gmail app password for SMTP
    domain = Column(String(100), nullable=True)  # legacy field used by existing dashboard
    linkedin_url = Column(String(512), nullable=True)
    gmail_connected = Column(Boolean, default=False)
    gmail_refresh_token = Column(Text, nullable=True)  # OAuth refresh token for Gmail API
    oauth_code_verifier = Column(Text, nullable=True)  # PKCE verifier (optional; for OAuth troubleshooting)
    gmail_last_history_id = Column(String(64), nullable=True)  # for Gmail History API polling
    status = Column(String(50), default="active")  # active | inactive
    # Rolling reputation from recent sends / bounces: healthy | warning | flagged
    email_health_status = Column(String(32), nullable=False, default="healthy", server_default="healthy")
    is_demo = Column(Boolean, default=False)
    # Explicit tag: this row is synthetic fixture data (must never appear in operator UI).
    is_fixture_test_data = Column(Boolean, default=False, nullable=False)
    emails_sent_today = Column(Integer, default=0, nullable=False)
    last_sent_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=utc_now)
