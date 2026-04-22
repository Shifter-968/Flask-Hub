-- =============================================================================
-- Announcements enhancements: alert level + expiry date
-- Run this in Supabase SQL editor.
-- =============================================================================

ALTER TABLE announcements
    ADD COLUMN IF NOT EXISTS alert_level VARCHAR(20) NOT NULL DEFAULT 'normal';

ALTER TABLE announcements
    ADD COLUMN IF NOT EXISTS expires_at DATE;

-- Optional hardening for valid values.
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1
        FROM information_schema.table_constraints
        WHERE constraint_name = 'announcements_alert_level_check'
          AND table_name = 'announcements'
    ) THEN
        ALTER TABLE announcements
        ADD CONSTRAINT announcements_alert_level_check
        CHECK (alert_level IN ('normal', 'high'));
    END IF;
END $$;

CREATE INDEX IF NOT EXISTS idx_announcements_school_created
    ON announcements(school_id, created_at DESC);

CREATE INDEX IF NOT EXISTS idx_announcements_school_expiry
    ON announcements(school_id, expires_at);

CREATE INDEX IF NOT EXISTS idx_announcements_school_alert
    ON announcements(school_id, alert_level);

-- =============================================================================
-- END
-- =============================================================================
