-- Align responses table with Response.gmail_message_id (reply_tracker dedupe).
ALTER TABLE responses ADD COLUMN IF NOT EXISTS gmail_message_id TEXT;
