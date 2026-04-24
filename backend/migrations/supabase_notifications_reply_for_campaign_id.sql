-- email_campaigns.id uses CHAR(36) (SQLAlchemy UuidType), NOT native PostgreSQL uuid.
-- Run in order in Supabase SQL Editor.

-- If a previous attempt created the wrong column type, remove it first:
-- ALTER TABLE notifications DROP CONSTRAINT IF EXISTS notifications_reply_for_campaign_id_fkey;
-- ALTER TABLE notifications DROP COLUMN IF EXISTS reply_for_campaign_id;

ALTER TABLE notifications
  ADD COLUMN IF NOT EXISTS reply_for_campaign_id character varying(36);

-- FK: column types must match email_campaigns.id (varchar/char, not uuid)
ALTER TABLE notifications
  DROP CONSTRAINT IF EXISTS notifications_reply_for_campaign_id_fkey;

ALTER TABLE notifications
  ADD CONSTRAINT notifications_reply_for_campaign_id_fkey
  FOREIGN KEY (reply_for_campaign_id)
  REFERENCES email_campaigns (id)
  ON DELETE SET NULL;

CREATE INDEX IF NOT EXISTS ix_notifications_reply_for_campaign_id
  ON notifications (reply_for_campaign_id);

CREATE UNIQUE INDEX IF NOT EXISTS uq_notifications_reply_campaign
  ON notifications (reply_for_campaign_id)
  WHERE type = 'reply' AND reply_for_campaign_id IS NOT NULL;

-- One-time cleanup: delete duplicate type=reply rows, keep oldest per reply_for_campaign_id
-- (Uncomment and run once if you already have duplicates.)
-- DELETE FROM notifications a
-- WHERE a.type = 'reply'
--   AND a.reply_for_campaign_id IS NOT NULL
--   AND EXISTS (
--     SELECT 1 FROM notifications b
--     WHERE b.type = 'reply'
--       AND b.reply_for_campaign_id = a.reply_for_campaign_id
--       AND b.created_at < a.created_at
--   );
