-- School Admin role scaffold
-- Run once in Supabase SQL editor

CREATE TABLE IF NOT EXISTS school_admins (
    id           BIGSERIAL PRIMARY KEY,
    user_id      INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    school_id    INTEGER NOT NULL REFERENCES schools(id) ON DELETE CASCADE,
    name         VARCHAR(150) NOT NULL,
    phone_number VARCHAR(80),
    created_at   TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE (user_id),
    UNIQUE (school_id, user_id)
);

CREATE INDEX IF NOT EXISTS idx_school_admins_school_id ON school_admins(school_id);
CREATE INDEX IF NOT EXISTS idx_school_admins_user_id ON school_admins(user_id);
