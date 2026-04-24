"""Assignment Pydantic schemas."""
from datetime import date, datetime
from typing import List, Optional
from uuid import UUID
from pydantic import BaseModel, Field


class AssignmentCreate(BaseModel):
    student_id: UUID
    hr_id: UUID


class AssignmentBulkCreate(BaseModel):
    """Admin selects student_id and list of hr_ids."""
    student_id: UUID
    hr_ids: List[UUID]
    min_hr_tier: Optional[str] = Field(
        None,
        description="Optional: reject HRs below this tier (A best). Example: B allows A and B only.",
    )


class AssignmentResponse(BaseModel):
    id: UUID
    student_id: UUID
    hr_id: UUID
    assigned_date: date
    status: str

    class Config:
        from_attributes = True
