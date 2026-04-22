-- Password reset and verification codes for auth flows.
CREATE TABLE IF NOT EXISTS auth_verification_codes (
    id BIGSERIAL PRIMARY KEY,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    purpose TEXT NOT NULL,
    channel TEXT NOT NULL,
    destination TEXT,
    code_hash TEXT NOT NULL,
    expires_at TIMESTAMPTZ NOT NULL,
    consumed_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_auth_codes_user_purpose_channel
    ON auth_verification_codes (user_id, purpose, channel, id DESC);

CREATE INDEX IF NOT EXISTS idx_auth_codes_expires_at
    ON auth_verification_codes (expires_at);
