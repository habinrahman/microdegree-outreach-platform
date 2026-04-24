"""One-off maintenance: reset exported_to_sheet flags (uses DATABASE_URL from env)."""
import os

from dotenv import load_dotenv
from sqlalchemy import create_engine, text

load_dotenv()

DATABASE_URL = os.getenv("DATABASE_URL")
if not DATABASE_URL or not DATABASE_URL.strip():
    raise SystemExit("DATABASE_URL must be set in the environment (e.g. backend/.env)")

engine = create_engine(DATABASE_URL)

BATCH_SIZE = 50

with engine.connect() as conn:
    print("Connected")

    while True:
        result = conn.execute(
            text(
                """
            SELECT id FROM email_campaigns
            WHERE reply_text IS NOT NULL
            AND exported_to_sheet = TRUE
            LIMIT :lim
        """
            ),
            {"lim": BATCH_SIZE},
        )

        ids = [row[0] for row in result]

        if not ids:
            break

        conn.execute(
            text(
                """
            UPDATE email_campaigns
            SET exported_to_sheet = FALSE
            WHERE id = ANY(:ids)
        """
            ),
            {"ids": ids},
        )

        conn.commit()

        print(f"Updated batch of {len(ids)}")

print("All flags reset successfully")
