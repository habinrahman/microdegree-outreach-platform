import smtplib
from email.message import EmailMessage
import os

# Absolute path of backend folder
BASE_DIR = os.path.dirname(os.path.abspath(__file__))


def send_email(student_email, app_password, hr_email, student_name, company, resume_path):

    msg = EmailMessage()

    msg["Subject"] = f"Application for Opportunities – {student_name}"
    msg["From"] = student_email
    msg["To"] = hr_email

    msg.set_content(f"""
Hello,

My name is {student_name}. I am reaching out to explore potential opportunities at {company}.

I have attached my resume for your consideration.

Looking forward to hearing from you.

Best regards,
{student_name}
""")

    # Convert resume path to absolute path
    full_resume_path = os.path.join(BASE_DIR, resume_path)

    with open(full_resume_path, "rb") as f:
        file_data = f.read()
        file_name = os.path.basename(full_resume_path)

    msg.add_attachment(
        file_data,
        maintype="application",
        subtype="pdf",
        filename=file_name
    )

    # Gmail SMTP
    with smtplib.SMTP_SSL("smtp.gmail.com", 465) as smtp:
        smtp.login(student_email, app_password)
        smtp.send_message(msg)

    return True
