"""HR Contact Pydantic schemas."""
from datetime import datetime
from typing import Optional
from uuid import UUID
from pydantic import BaseModel


class HRContactBase(BaseModel):
    name: str
    company: str
    email: str
    linkedin_url: Optional[str] = None
    designation: Optional[str] = None
    city: Optional[str] = None
    source: Optional[str] = None
    status: str = "active"


class HRContactCreate(HRContactBase):
    pass


class HRContactUpdate(BaseModel):
    name: Optional[str] = None
    company: Optional[str] = None
    email: Optional[str] = None
    linkedin_url: Optional[str] = None
    designation: Optional[str] = None
    city: Optional[str] = None
    source: Optional[str] = None
    status: Optional[str] = None


class HRContactResponse(HRContactBase):
    id: UUID
    created_at: datetime
    sent: bool = False
    replied: bool = False
    bounce_count: int = 0
    last_bounced_at: Optional[datetime] = None
    score: Optional[float] = None

    class Config:
        from_attributes = True
