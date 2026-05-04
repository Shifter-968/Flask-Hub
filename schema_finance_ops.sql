-- ============================================================================
-- Finance Operations Schema (fees, balances, ledger, reminders)
-- Run this in Supabase SQL editor.
-- ============================================================================

CREATE TABLE IF NOT EXISTS student_finance_accounts (
    id                BIGSERIAL PRIMARY KEY,
    school_id         INTEGER NOT NULL REFERENCES schools(id) ON DELETE CASCADE,
    student_user_id   INTEGER,
    parent_user_id    INTEGER,
    student_name      VARCHAR(180) NOT NULL,
    student_role      VARCHAR(20) NOT NULL DEFAULT 'learner',
    reference_code    VARCHAR(40) UNIQUE NOT NULL,
    opening_balance   NUMERIC(12,2) NOT NULL DEFAULT 0,
    current_balance   NUMERIC(12,2) NOT NULL DEFAULT 0,
    status            VARCHAR(20) NOT NULL DEFAULT 'active',
    created_at        TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at        TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT chk_student_finance_role CHECK (student_role IN ('learner', 'student')),
    CONSTRAINT chk_student_finance_status CHECK (status IN ('active', 'closed', 'suspended'))
);

CREATE INDEX IF NOT EXISTS idx_student_finance_accounts_school
    ON student_finance_accounts (school_id, id DESC);

CREATE INDEX IF NOT EXISTS idx_student_finance_accounts_parent
    ON student_finance_accounts (parent_user_id, school_id);

CREATE TABLE IF NOT EXISTS student_finance_transactions (
    id                 BIGSERIAL PRIMARY KEY,
    school_id          INTEGER NOT NULL REFERENCES schools(id) ON DELETE CASCADE,
    account_id         BIGINT NOT NULL REFERENCES student_finance_accounts(id) ON DELETE CASCADE,
    txn_type           VARCHAR(20) NOT NULL,
    amount             NUMERIC(12,2) NOT NULL,
    method             VARCHAR(40),
    reference          VARCHAR(120),
    notes              TEXT,
    created_by_user_id INTEGER,
    created_by_role    VARCHAR(40),
    transacted_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT chk_student_finance_txn_type CHECK (txn_type IN ('charge', 'payment', 'adjustment')),
    CONSTRAINT chk_student_finance_amount_positive CHECK (amount > 0)
);

CREATE INDEX IF NOT EXISTS idx_student_finance_txn_school
    ON student_finance_transactions (school_id, transacted_at DESC);

CREATE INDEX IF NOT EXISTS idx_student_finance_txn_account
    ON student_finance_transactions (account_id, transacted_at DESC);

CREATE TABLE IF NOT EXISTS fee_reminder_runs (
    id           BIGSERIAL PRIMARY KEY,
    school_id    INTEGER NOT NULL REFERENCES schools(id) ON DELETE CASCADE,
    account_id   BIGINT NOT NULL REFERENCES student_finance_accounts(id) ON DELETE CASCADE,
    channel      VARCHAR(30) NOT NULL DEFAULT 'email',
    status       VARCHAR(20) NOT NULL DEFAULT 'sent',
    message      TEXT,
    created_at   TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_fee_reminder_runs_school
    ON fee_reminder_runs (school_id, created_at DESC);
