from pathlib import Path
from dotenv import load_dotenv
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError

load_dotenv(dotenv_path=Path(__file__).resolve().parent.parent / ".env")

from app.database.config import engine, Base
from app.models import (
    Student,
    HRContact,
    Assignment,
    Response,
    Interview,
    EmailCampaign,
    Campaign,
    Notification,
    AuditLog,
    HRIgnored,
)


def init_db() -> None:
    try:
        print("Connecting to database...")
        with engine.connect() as connection:
            connection.execute(text("SELECT 1"))

        print("Creating tables...")
        Base.metadata.create_all(bind=engine)
        print("Tables created successfully!")
    except SQLAlchemyError as error:
        print(f"Database initialization failed: {error}")


if __name__ == "__main__":
    init_db()
