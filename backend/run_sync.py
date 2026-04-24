from app.database.config import SessionLocal
from app.services.sheet_sync import sync_new_replies
from app.services.blocked_hr_sync import sync_blocked_hrs

db = SessionLocal()

print("🚀 Running reply sync...")
sync_new_replies(db)

print("🚀 Running blocked HR sync...")
sync_blocked_hrs(db)

print("✅ DONE")