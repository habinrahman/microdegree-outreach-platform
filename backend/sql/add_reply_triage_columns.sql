-- Production recovery: run once against your Postgres (Supabase SQL editor / psql).
-- VERIFY after:
-- SELECT column_name FROM information_schema.columns WHERE table_name = 'email_campaigns';

ALTER TABLE email_campaigns
  ADD COLUMN IF NOT EXISTS reply_workflow_status VARCHAR(50) DEFAULT 'OPEN';

ALTER TABLE email_campaigns
  ADD COLUMN IF NOT EXISTS reply_admin_notes TEXT;
