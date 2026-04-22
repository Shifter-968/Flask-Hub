-- Staff role scaffold for authenticated non-teaching staff accounts
-- Run once in Supabase SQL editor

CREATE TABLE IF NOT EXISTS staff (
    id           BIGSERIAL PRIMARY KEY,
    user_id      INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    school_id    INTEGER NOT NULL REFERENCES schools(id) ON DELETE CASCADE,
    name         VARCHAR(150) NOT NULL,
    department   VARCHAR(150),
    phone_number VARCHAR(80),
    created_at   TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE (user_id)
);

ALTER TABLE staff ADD COLUMN IF NOT EXISTS school_id INTEGER REFERENCES schools(id) ON DELETE CASCADE;
ALTER TABLE staff ADD COLUMN IF NOT EXISTS user_id INTEGER REFERENCES users(id) ON DELETE CASCADE;
ALTER TABLE staff ADD COLUMN IF NOT EXISTS name VARCHAR(150);
ALTER TABLE staff ADD COLUMN IF NOT EXISTS department VARCHAR(150);
ALTER TABLE staff ADD COLUMN IF NOT EXISTS phone_number VARCHAR(80);
ALTER TABLE staff ADD COLUMN IF NOT EXISTS created_at TIMESTAMPTZ DEFAULT NOW();

CREATE UNIQUE INDEX IF NOT EXISTS idx_staff_user_id_unique ON staff(user_id);
CREATE INDEX IF NOT EXISTS idx_staff_school_id ON staff(school_id);