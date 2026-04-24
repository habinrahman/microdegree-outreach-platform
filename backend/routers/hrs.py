from fastapi import APIRouter, Depends, UploadFile, File
from sqlalchemy.orm import Session
from database import SessionLocal
import models
import pandas as pd

router = APIRouter(prefix="/hrs", tags=["hrs"])


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


# Add HR manually
@router.post("/")
def create_hr(company: str, hr_name: str, email: str, domain: str, db: Session = Depends(get_db)):

    hr = models.HR(
        company=company,
        hr_name=hr_name,
        email=email,
        domain=domain
    )

    db.add(hr)
    db.commit()
    db.refresh(hr)

    return {"message": "HR added successfully"}


# Get all HR contacts
@router.get("/")
def get_hrs(db: Session = Depends(get_db)):
    return db.query(models.HR).all()


# Bulk upload HR CSV
@router.post("/upload")
def upload_hr_csv(file: UploadFile = File(...), db: Session = Depends(get_db)):

    df = pd.read_csv(file.file)

    added = 0

    for _, row in df.iterrows():

        hr = models.HR(
            company=row["company"],
            hr_name=row["hr_name"],
            email=row["email"],
            domain=row["domain"]
        )

        db.add(hr)
        added += 1

    db.commit()

    return {
        "message": "HR CSV uploaded successfully",
        "total_added": added
    }
