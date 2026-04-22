-- =============================================================================
-- Contact Messages Inbox
-- Run this in Supabase SQL editor.
-- =============================================================================

CREATE TABLE IF NOT EXISTS contact_messages (
    id BIGSERIAL PRIMARY KEY,
    school_id INTEGER REFERENCES schools(id) ON DELETE CASCADE,
    source_scope VARCHAR(30) NOT NULL DEFAULT 'main_hub',
    source_site VARCHAR(200),
    sender_name VARCHAR(180) NOT NULL,
    sender_email VARCHAR(180) NOT NULL,
    sender_phone VARCHAR(80),
    message TEXT NOT NULL,
    status VARCHAR(30) NOT NULL DEFAULT 'new',
    page_url TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_contact_messages_created_at
    ON contact_messages(created_at DESC);

CREATE INDEX IF NOT EXISTS idx_contact_messages_school
    ON contact_messages(school_id, created_at DESC);

CREATE INDEX IF NOT EXISTS idx_contact_messages_scope
    ON contact_messages(source_scope, created_at DESC);

-- =============================================================================
-- END
-- =============================================================================
