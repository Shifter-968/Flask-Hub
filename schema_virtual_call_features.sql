-- Virtual classroom call attendance schema
-- Run this in Supabase SQL editor to enable persistent meeting analytics.

CREATE TABLE IF NOT EXISTS virtual_call_attendance_logs (
    id BIGSERIAL PRIMARY KEY,
    classroom_id INTEGER NOT NULL,
    call_post_id INTEGER NOT NULL,
    actor_id VARCHAR(64),
    actor_role VARCHAR(30),
    actor_name VARCHAR(140),
    event_type VARCHAR(20) NOT NULL,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_virtual_call_attendance_classroom_call
    ON virtual_call_attendance_logs(classroom_id, call_post_id, created_at DESC);

CREATE INDEX IF NOT EXISTS idx_virtual_call_attendance_actor
    ON virtual_call_attendance_logs(actor_id, created_at DESC);
