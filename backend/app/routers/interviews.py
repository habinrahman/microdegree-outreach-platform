"""Interview CRUD – track interviews from HR responses (Part 3)."""
from uuid import UUID
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.auth import require_api_key
from app.database import get_db
from app.models import Interview
from app.schemas.interview import InterviewCreate, InterviewUpdate, InterviewResponse

router = APIRouter(prefix="/interviews", tags=["interviews"], dependencies=[Depends(require_api_key)])


@router.get("/", response_model=list[InterviewResponse])
def list_interviews(
    db: Session = Depends(get_db),
    student_id: UUID | None = None,
    hr_id: UUID | None = None,
    status: str | None = None,
):
    """List interviews, optionally filtered by student_id, hr_id, or status."""
    q = db.query(Interview).order_by(Interview.interview_date.desc(), Interview.created_at.desc())
    if student_id is not None:
        q = q.filter(Interview.student_id == student_id)
    if hr_id is not None:
        q = q.filter(Interview.hr_id == hr_id)
    if status:
        q = q.filter(Interview.status == status)
    return q.all()


@router.post("/", response_model=InterviewResponse)
def create_interview(body: InterviewCreate, db: Session = Depends(get_db)):
    """Create a new interview record."""
    obj = Interview(
        student_id=body.student_id,
        hr_id=body.hr_id,
        company=body.company,
        interview_date=body.interview_date,
        status=body.status,
        notes=body.notes,
    )
    db.add(obj)
    db.commit()
    db.refresh(obj)
    return obj


@router.get("/{interview_id}", response_model=InterviewResponse)
def get_interview(interview_id: UUID, db: Session = Depends(get_db)):
    """Get one interview by id."""
    obj = db.query(Interview).filter(Interview.id == interview_id).first()
    if not obj:
        raise HTTPException(status_code=404, detail="Interview not found")
    return obj


@router.put("/{interview_id}", response_model=InterviewResponse)
def update_interview(interview_id: UUID, body: InterviewUpdate, db: Session = Depends(get_db)):
    """Update an interview (status, date, notes, company)."""
    obj = db.query(Interview).filter(Interview.id == interview_id).first()
    if not obj:
        raise HTTPException(status_code=404, detail="Interview not found")
    data = body.model_dump(exclude_unset=True)
    for k, v in data.items():
        setattr(obj, k, v)
    db.commit()
    db.refresh(obj)
    return obj


@router.delete("/{interview_id}")
def delete_interview(interview_id: UUID, db: Session = Depends(get_db)):
    """Delete an interview record."""
    obj = db.query(Interview).filter(Interview.id == interview_id).first()
    if not obj:
        raise HTTPException(status_code=404, detail="Interview not found")
    db.delete(obj)
    db.commit()
    return {"message": "Deleted"}
