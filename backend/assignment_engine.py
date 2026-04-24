from sqlalchemy.orm import Session
import models
from email_sender import send_email
import time


def run_outreach(db: Session):

    students = db.query(models.Student).all()

    results = []

    for student in students:

        hrs = db.query(models.HR).filter(
            models.HR.domain == student.domain
        ).all()

        for hr in hrs:

            send_email(
                student.email,
                student.app_password,
                hr.email,
                student.name,
                hr.company,
                student.resume
            )

            results.append({
                "student": student.name,
                "company": hr.company
            })

            time.sleep(20)  # rate limit

    return results
