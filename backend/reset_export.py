from app.database.config import SessionLocal
from app.models import EmailCampaign

db = SessionLocal()

updated = db.query(EmailCampaign).update({
    "exported_to_sheet": False
})

db.commit()

print(f"✅ Reset done. Rows updated: {updated}")