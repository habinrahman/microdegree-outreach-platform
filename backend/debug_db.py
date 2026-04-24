from app.database.config import SessionLocal
from app.models import EmailCampaign

db = SessionLocal()

print("---- SAMPLE DATA ----")

rows = db.query(
    EmailCampaign.status,
    EmailCampaign.reply_status,
    EmailCampaign.delivery_status
).all()

for r in rows[:20]:
    print(r)

print("\n---- COUNTS ----")

print("TOTAL replied:",
      db.query(EmailCampaign).filter(
          EmailCampaign.status == "replied"
      ).count())

print("TOTAL all:",
      db.query(EmailCampaign).count())