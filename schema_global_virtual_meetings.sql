-- Global virtual meetings (school-wide, password + meeting code protected)
CREATE TABLE IF NOT EXISTS global_virtual_meetings (
    id BIGSERIAL PRIMARY KEY,
    school_id INTEGER NOT NULL,
    title VARCHAR(200) NOT NULL,
    room_name VARCHAR(255) NOT NULL,
    meeting_code VARCHAR(24) NOT NULL,
    password_hash VARCHAR(128) NOT NULL,
    password_sealed TEXT,
    created_by VARCHAR(160),
    created_by_role VARCHAR(40),
    created_by_id VARCHAR(64),
    created_at TIMESTAMPTZ DEFAULT NOW(),
    scheduled_start TIMESTAMPTZ,
    scheduled_end TIMESTAMPTZ,
    ended_at TIMESTAMPTZ,
    password_rotated_at TIMESTAMPTZ
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_global_virtual_meetings_code
    ON global_virtual_meetings (school_id, meeting_code);

CREATE INDEX IF NOT EXISTS idx_global_virtual_meetings_created
    ON global_virtual_meetings (school_id, created_at DESC);
