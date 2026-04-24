-- Prevent duplicate campaigns for the same student + HR pair.
-- Run in Supabase SQL Editor.

-- 1) Optional pre-check: identify duplicates that must be resolved first.
SELECT
    student_id,
    hr_id,
    COUNT(*) AS duplicate_count
FROM email_campaigns
GROUP BY student_id, hr_id
HAVING COUNT(*) > 1;

-- 2) Add DB-level unique protection (idempotent).
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1
        FROM pg_constraint
        WHERE conname = 'uq_student_hr'
    ) THEN
        ALTER TABLE email_campaigns
        ADD CONSTRAINT uq_student_hr UNIQUE (student_id, hr_id);
    END IF;
END $$;

-- NOTE:
-- If follow-up campaigns per pair are needed later, replace with:
-- UNIQUE (student_id, hr_id, sequence_number)
