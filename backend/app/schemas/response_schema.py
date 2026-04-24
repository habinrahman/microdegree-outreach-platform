from datetime import date
from uuid import UUID
from pydantic import BaseModel


class ResponseCreate(BaseModel):
    student_id: UUID
    hr_id: UUID
    response_date: date
    response_type: str  # positive | negative | refer_contact | not_hiring | other
    notes: str | None = None
