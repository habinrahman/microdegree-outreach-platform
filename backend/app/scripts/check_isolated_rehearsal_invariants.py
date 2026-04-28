from __future__ import annotations

import os
from dotenv import load_dotenv
from sqlalchemy import text

from app.database.config import engine


def main() -> None:
    load_dotenv()
    with engine.connect() as c:
        sp = c.execute(text("show search_path")).scalar_one()
        print("search_path:", sp)

        students = c.execute(text("select coalesce(email_health_status,'(null)') as s, count(1) from students group by 1 order by 2 desc")).fetchall()
        print("student_email_health_counts:", students)

        flagged = c.execute(text("select count(1) from students where lower(coalesce(email_health_status,'')) = 'flagged'")).scalar_one()
        print("flagged_students:", int(flagged))

        suppressed = c.execute(text("select count(1) from outbound_suppressions where is_active is true")).scalar_one()
        print("active_suppressions:", int(suppressed))

        canc = c.execute(text("select count(1) from email_campaigns where status='cancelled' and coalesce(error,'') like 'suppressed:%'")).scalar_one()
        print("suppressed_campaign_cancellations:", int(canc))

        processing = c.execute(text("select count(1) from email_campaigns where status='processing'")).scalar_one()
        print("processing_campaigns:", int(processing))


if __name__ == "__main__":
    main()

