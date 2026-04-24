from datetime import date
from uuid import UUID
from pydantic import BaseModel


class InterviewBase(BaseModel):
    student_id: UUID
    hr_id: UUID
    company: str
    interview_date: date | None = None
    status: str  # interview_scheduled | interview_completed | offer_received | rejected
    notes: str | None = None


class InterviewCreate(InterviewBase):
    pass


class InterviewUpdate(BaseModel):
    company: str | None = None
    interview_date: date | None = None
    status: str | None = None
    notes: str | None = None


class InterviewResponse(BaseModel):
    id: UUID
    student_id: UUID
    hr_id: UUID
    company: str
    interview_date: date | None
    status: str
    notes: str | None

    class Config:
        from_attributes = True
