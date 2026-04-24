"""Pydantic schemas for email campaign updates."""
from uuid import UUID

from pydantic import BaseModel, Field


class CampaignBulkPatchBody(BaseModel):
    """Bulk update campaign rows (pending/scheduled/processing → paused or cancelled)."""

    campaign_ids: list[UUID] = Field(..., min_length=1, max_length=500)
    status: str = Field(..., description="paused or cancelled")


class CampaignUpdateBody(BaseModel):
    """Update content for a scheduled campaign only."""

    subject: str = Field(..., min_length=1, max_length=512)
    body: str = Field(..., description="Email body (plain text)")
