from fastapi import APIRouter, Depends, UploadFile, File, Form
from sqlalchemy.orm import Session
from database import SessionLocal
import models
import shutil

router = APIRouter(prefix="/students", tags=["students"])


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


@router.post("/")
def create_student(
    name: str = Form(...),
    email: str = Form(...),
    app_password: str = Form(...),
    domain: str = Form(...),
    resume: UploadFile = File(...),
    db: Session = Depends(get_db)
):

    resume_path = f"resumes/{resume.filename}"

    with open(resume_path, "wb") as buffer:
        shutil.copyfileobj(resume.file, buffer)

    student = models.Student(
        name=name,
        email=email,
        app_password=app_password,
        domain=domain,
        resume=resume_path,
        status="active"
    )

    db.add(student)
    db.commit()
    db.refresh(student)

    return {"message": "Student added successfully"}

@router.get("/")
def get_students(db: Session = Depends(get_db)):
    students = db.query(models.Student).all()
    return students
