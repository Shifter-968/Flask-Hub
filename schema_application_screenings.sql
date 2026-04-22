-- PostgreSQL / Supabase schema for persisted AI application screenings

CREATE TABLE IF NOT EXISTS application_screenings (
    id               BIGSERIAL PRIMARY KEY,
    application_ref  VARCHAR(16) NOT NULL REFERENCES online_applications(ref) ON DELETE CASCADE,
    school_id        INTEGER NOT NULL REFERENCES schools(id) ON DELETE CASCADE,
    screening_score  NUMERIC(5,2) NOT NULL,
    recommendation   VARCHAR(30) NOT NULL,
    summary          TEXT,
    strengths        JSONB NOT NULL DEFAULT '[]'::jsonb,
    concerns         JSONB NOT NULL DEFAULT '[]'::jsonb,
    missing_items    JSONB NOT NULL DEFAULT '[]'::jsonb,
    screening_source VARCHAR(30) NOT NULL DEFAULT 'rules_only',
    model            VARCHAR(80),
    created_by       VARCHAR(100),
    created_at       TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_application_screenings_ref_created
    ON application_screenings(application_ref, created_at DESC);

CREATE INDEX IF NOT EXISTS idx_application_screenings_school_created
    ON application_screenings(school_id, created_at DESC);
