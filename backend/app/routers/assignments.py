"""Assignment API - assign HR contacts to students."""
from uuid import UUID
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.auth import require_api_key
from app.database import get_db
from app.models import Assignment, Student
from app.schemas.assignment import AssignmentBulkCreate, AssignmentResponse
from app.services.assignment_service import validate_and_assign

router = APIRouter(prefix="/assignments", tags=["assignments"], dependencies=[Depends(require_api_key)])


@router.post("")
def create_assignments(payload: AssignmentBulkCreate, db: Session = Depends(get_db)):
    """
    Assign HR contacts to a student.
    The same HR may be assigned to many students; duplicate (student, hr) pairs are rejected.
    Rejects if student is inactive.
    """
    student = db.query(Student).filter(Student.id == payload.student_id).first()
    if not student:
        raise HTTPException(status_code=404, detail="Student not found")
    if student.status != "active":
        raise HTTPException(
            status_code=400,
            detail="Inactive students cannot receive new HR assignments",
        )
    if not payload.hr_ids:
        return {
            "created": [],
            "rejected_already_assigned": [],
            "rejected_not_found": [],
            "rejected_invalid_hr": [],
            "rejected_low_tier": [],
        }

    created, rejected_already, rejected_not_found, rejected_invalid, rejected_low_tier = validate_and_assign(
        db, payload.student_id, payload.hr_ids, min_hr_tier=payload.min_hr_tier
    )
    return {
        "created": [AssignmentResponse.model_validate(a) for a in created],
        "rejected_already_assigned": [str(h) for h in rejected_already],
        "rejected_not_found": [str(h) for h in rejected_not_found],
        "rejected_invalid_hr": [str(h) for h in rejected_invalid],
        "rejected_low_tier": [str(h) for h in rejected_low_tier],
    }


@router.get("", response_model=list[AssignmentResponse])
def list_assignments(
    student_id: UUID | None = None,
    hr_id: UUID | None = None,
    status: str | None = None,
    db: Session = Depends(get_db),
):
    """List assignments with optional filters."""
    q = db.query(Assignment).order_by(Assignment.assigned_date.desc())
    if student_id is not None:
        q = q.filter(Assignment.student_id == student_id)
    if hr_id is not None:
        q = q.filter(Assignment.hr_id == hr_id)
    if status is not None:
        q = q.filter(Assignment.status == status)
    return q.all()
