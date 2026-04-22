-- =============================================================================
-- Notifications: in-app + delivery logs (email/sms)
-- Run this in Supabase SQL editor.
-- =============================================================================

CREATE TABLE IF NOT EXISTS user_notifications (
    id BIGSERIAL PRIMARY KEY,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    title VARCHAR(140) NOT NULL,
    message TEXT NOT NULL,
    notification_type VARCHAR(60) NOT NULL DEFAULT 'general',
    priority VARCHAR(20) NOT NULL DEFAULT 'normal',
    is_read BOOLEAN NOT NULL DEFAULT FALSE,
    read_at TIMESTAMPTZ,
    meta_json JSONB,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS notification_deliveries (
    id BIGSERIAL PRIMARY KEY,
    notification_id BIGINT REFERENCES user_notifications(id) ON DELETE SET NULL,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    channel VARCHAR(20) NOT NULL,
    -- in_app | email | sms
    status VARCHAR(20) NOT NULL,
    -- sent | failed
    detail TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_user_notifications_user_created
    ON user_notifications(user_id, created_at DESC);

CREATE INDEX IF NOT EXISTS idx_user_notifications_unread
    ON user_notifications(user_id, is_read);

CREATE INDEX IF NOT EXISTS idx_notification_deliveries_user
    ON notification_deliveries(user_id, created_at DESC);

CREATE INDEX IF NOT EXISTS idx_notification_deliveries_notification
    ON notification_deliveries(notification_id, created_at DESC);

-- =============================================================================
-- END
-- =============================================================================
