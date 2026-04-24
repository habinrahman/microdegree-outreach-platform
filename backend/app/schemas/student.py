"""Student Pydantic schemas."""
from datetime import datetime
from typing import Optional
from uuid import UUID
from pydantic import BaseModel, ConfigDict


class StudentPublic(BaseModel):
    """Safe API shape — no app_password, no gmail_refresh_token (or other secrets)."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    name: str
    gmail_address: str
    status: str = "active"
    domain: Optional[str] = None
    gmail_connected: bool = False
    connection_type: Optional[str] = None  # "OAuth" | "SMTP" | None
    is_demo: bool = False
    experience_years: int = 0
    skills: Optional[str] = None
    resume_drive_file_id: Optional[str] = None
    resume_file_name: Optional[str] = None
    resume_path: Optional[str] = None
    linkedin_url: Optional[str] = None
    created_at: datetime
    emails_sent_today: int = 0
    last_sent_at: Optional[datetime] = None
    email_health_status: str = "healthy"


class StudentCreate(BaseModel):
    """Create payload — app password write-only, never returned on responses."""

    name: str
    gmail_address: str
    is_demo: bool = False
    experience_years: int = 0
    skills: Optional[str] = None
    resume_drive_file_id: Optional[str] = None
    resume_file_name: Optional[str] = None
    resume_path: Optional[str] = None
    app_password: Optional[str] = None
    domain: Optional[str] = None
    linkedin_url: Optional[str] = None
    gmail_connected: bool = False
    status: str = "active"


class StudentUpdate(BaseModel):
    """Partial update — only allowlisted fields applied in the router (no mass setattr)."""

    name: Optional[str] = None
    is_demo: Optional[bool] = None
    gmail_address: Optional[str] = None
    experience_years: Optional[int] = None
    skills: Optional[str] = None
    resume_drive_file_id: Optional[str] = None
    resume_file_name: Optional[str] = None
    resume_path: Optional[str] = None
    app_password: Optional[str] = None
    domain: Optional[str] = None
    linkedin_url: Optional[str] = None
    gmail_connected: Optional[bool] = None
    status: Optional[str] = None


# Backward-compatible names
StudentSafe = StudentPublic
StudentResponse = StudentPublic


class StudentHealthRow(BaseModel):
    student_id: str
    email: str
    health_status: str
    failure_rate: float
    blocked_count: int
