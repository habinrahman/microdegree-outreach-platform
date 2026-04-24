"""Unified campaign view schema (API contracts)."""
from __future__ import annotations

from datetime import datetime
from typing import Optional

from pydantic import BaseModel


class UnifiedCampaignView(BaseModel):
    id: str
    student_name: str
    company: Optional[str] = None
    hr_email: Optional[str] = None
    subject: Optional[str] = None

    status: str
    reply_status: Optional[str] = None
    delivery_status: Optional[str] = None

    reply_text: Optional[str] = None
    replied_at: Optional[datetime] = None

    sent_at: Optional[datetime] = None
