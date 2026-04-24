"""Minimal script to verify DATABASE_URL connectivity."""
from pathlib import Path

from dotenv import load_dotenv
from sqlalchemy import text

load_dotenv(dotenv_path=Path(__file__).resolve().parent.parent / ".env")

from app.database.config import engine


def main() -> None:
    try:
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        print("Connection successful")
    except Exception as e:
        print(f"Database error ({type(e).__name__}): {e}")


if __name__ == "__main__":
    main()
