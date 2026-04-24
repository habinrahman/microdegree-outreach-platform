from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from database import SessionLocal
import models
from email_sender import send_email

router = APIRouter(prefix="/outreach", tags=["outreach"])


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


@router.post("/send")
def send_outreach(student_id: int, hr_id: int, db: Session = Depends(get_db)):

    student = db.query(models.Student).filter(models.Student.id == student_id).first()
    hr = db.query(models.HR).filter(models.HR.id == hr_id).first()

    send_email(
        student.email,
        student.app_password,
        hr.email,
        student.name,
        hr.company,
        student.resume
    )

    return {"message": "Email sent successfully"}
from assignment_engine import run_outreach


@router.post("/start")
def start_outreach(db: Session = Depends(get_db)):

    results = run_outreach(db)

    return {
        "message": "Outreach completed",
        "emails_sent": results
    }
@router.get("/logs")
def get_logs(db: Session = Depends(get_db)):
    return db.query(models.Outreach).all()

@router.get("/stats")
def get_stats(db: Session = Depends(get_db)):

    students_count = db.query(models.Student).count()
    hrs_count = db.query(models.HR).count()
    emails_sent = db.query(models.Outreach).count()

    success_rate = 0
    if emails_sent > 0:
        success_rate = 100

    return {
        "students": students_count,
        "hrs": hrs_count,
        "emails_sent": emails_sent,
        "success_rate": success_rate
    }
