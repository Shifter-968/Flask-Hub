-- =============================================================================
-- Online Application System – Database Schema
-- Run this in your Supabase SQL editor to create the required tables.
-- =============================================================================

-- Applications master table
CREATE TABLE IF NOT EXISTS online_applications (
    id            BIGSERIAL PRIMARY KEY,
    ref           VARCHAR(16)  UNIQUE NOT NULL,
    school_id     INTEGER      REFERENCES schools(id) ON DELETE CASCADE,
    status        VARCHAR(30)  NOT NULL DEFAULT 'draft',
    -- Status values: draft | submitted | under_review | missing_docs | accepted | rejected

    -- Step 1: Programme Selection
    academic_year         VARCHAR(20),
    qualification         VARCHAR(300),
    section               VARCHAR(100),

    -- Step 2: Personal Information
    title                 VARCHAR(20),
    surname               VARCHAR(100),
    first_names           VARCHAR(200),
    dob                   DATE,
    gender                VARCHAR(20),
    nationality           VARCHAR(100),
    national_id           VARCHAR(60),
    disability            VARCHAR(10),
    disability_description TEXT,
    marital_status        VARCHAR(30),
    region                VARCHAR(100),
    email                 VARCHAR(200),
    phone                 VARCHAR(30),

    -- Step 3: Guardian / Responsible Payer
    payer_title           VARCHAR(20),
    payer_surname         VARCHAR(100),
    payer_relationship    VARCHAR(60),
    payer_tel             VARCHAR(30),
    payer_mobile          VARCHAR(30),
    payer_email           VARCHAR(200),
    payer_address         TEXT,

    -- Step 4: Academic Background
    highest_qualification VARCHAR(200),
    institution_attended  VARCHAR(200),
    year_completed        VARCHAR(10),
    subjects_passed       TEXT,
    has_rpl               BOOLEAN DEFAULT FALSE,
    rpl_details           TEXT,

    -- Step 6: Payment Confirmation
    payment_reference     VARCHAR(100),
    payment_date          DATE,
    payment_amount        NUMERIC(10,2),
    payment_bank          VARCHAR(100),

    -- Step 7: Declaration
    declaration_accepted  BOOLEAN DEFAULT FALSE,
    submitted_at          TIMESTAMPTZ,

    -- Admin processing
    admin_notes           TEXT,
    reviewed_by           VARCHAR(100),
    reviewed_at           TIMESTAMPTZ,

    -- Meta
    created_at            TIMESTAMPTZ DEFAULT NOW(),
    updated_at            TIMESTAMPTZ DEFAULT NOW()
);

-- Uploaded supporting documents
CREATE TABLE IF NOT EXISTS online_application_docs (
    id               BIGSERIAL PRIMARY KEY,
    application_ref  VARCHAR(16) REFERENCES online_applications(ref) ON DELETE CASCADE,
    doc_type         VARCHAR(60)  NOT NULL,
    -- Doc types: national_id_doc | form5_results | payment_slip | certificates
    file_url         TEXT         NOT NULL,
    original_name    VARCHAR(255),
    uploaded_at      TIMESTAMPTZ  DEFAULT NOW()
);

-- Indexes
CREATE INDEX IF NOT EXISTS idx_online_applications_school  ON online_applications(school_id);
CREATE INDEX IF NOT EXISTS idx_online_applications_status  ON online_applications(status);
CREATE INDEX IF NOT EXISTS idx_online_applications_email   ON online_applications(email);
CREATE INDEX IF NOT EXISTS idx_online_app_docs_ref         ON online_application_docs(application_ref);

-- =============================================================================
-- END
-- =============================================================================
