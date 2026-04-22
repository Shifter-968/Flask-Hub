-- Portal Results and Reports schema additions
-- Run in Supabase SQL editor

-- 1) Performance records (tests, projects, exams)
CREATE TABLE IF NOT EXISTS performance_records (
    id BIGSERIAL PRIMARY KEY,
    student_id INTEGER NOT NULL,
    student_type VARCHAR(20) NOT NULL CHECK (student_type IN ('student', 'learner')),
    classroom_id INTEGER NOT NULL REFERENCES classrooms(id) ON DELETE CASCADE,
    subject_name VARCHAR(200) NOT NULL,
    subject_ref_id INTEGER,
    subject_ref_type VARCHAR(20),
    assignment_name VARCHAR(200) NOT NULL,
    assignment_type VARCHAR(20) NOT NULL CHECK (assignment_type IN ('test', 'project', 'exam')),
    marks_scored NUMERIC(8,2) NOT NULL,
    total_marks NUMERIC(8,2) NOT NULL,
    percentage NUMERIC(6,2) NOT NULL,
    teacher_comment TEXT,
    cycle_label VARCHAR(60),
    term_label VARCHAR(60),
    academic_year VARCHAR(20),
    recorded_by_id INTEGER,
    recorded_by_type VARCHAR(20),
    created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_perf_student_class
    ON performance_records(student_id, student_type, classroom_id);

CREATE INDEX IF NOT EXISTS idx_perf_cycle
    ON performance_records(cycle_label, academic_year);

-- 2) Term/Semester results
CREATE TABLE IF NOT EXISTS term_results (
    id BIGSERIAL PRIMARY KEY,
    student_id INTEGER NOT NULL,
    student_type VARCHAR(20) NOT NULL CHECK (student_type IN ('student', 'learner')),
    classroom_id INTEGER NOT NULL REFERENCES classrooms(id) ON DELETE CASCADE,
    subject_name VARCHAR(200) NOT NULL,
    subject_ref_id INTEGER,
    subject_ref_type VARCHAR(20),
    overall_mark NUMERIC(8,2) NOT NULL,
    total_possible NUMERIC(8,2) NOT NULL,
    percentage NUMERIC(6,2) NOT NULL,
    symbol VARCHAR(10) NOT NULL,
    teacher_comment TEXT,
    term_label VARCHAR(60),
    academic_year VARCHAR(20),
    recorded_by_id INTEGER,
    recorded_by_type VARCHAR(20),
    created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_term_student_class
    ON term_results(student_id, student_type, classroom_id);

CREATE INDEX IF NOT EXISTS idx_term_cycle
    ON term_results(term_label, academic_year);

-- 3) Stored report documents (PDF-ready history records)
CREATE TABLE IF NOT EXISTS term_report_documents (
    id BIGSERIAL PRIMARY KEY,
    classroom_id INTEGER NOT NULL REFERENCES classrooms(id) ON DELETE CASCADE,
    student_id INTEGER NOT NULL,
    student_type VARCHAR(20) NOT NULL CHECK (student_type IN ('student', 'learner')),
    overall_percentage NUMERIC(6,2),
    teacher_comment TEXT,
    term_label VARCHAR(60),
    academic_year VARCHAR(20),
    school_type VARCHAR(40),
    template_variant VARCHAR(30),
    report_rows JSONB,
    pdf_file_path TEXT,
    created_by_id INTEGER,
    created_by_type VARCHAR(20),
    created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_report_student
    ON term_report_documents(student_id, student_type);

CREATE INDEX IF NOT EXISTS idx_report_cycle
    ON term_report_documents(term_label, academic_year);

-- 4) Optional school switches for automation controls
ALTER TABLE schools
    ADD COLUMN IF NOT EXISTS active_term VARCHAR(60),
    ADD COLUMN IF NOT EXISTS active_semester VARCHAR(60),
    ADD COLUMN IF NOT EXISTS active_academic_year VARCHAR(20),
    ADD COLUMN IF NOT EXISTS portal_marks_open BOOLEAN DEFAULT TRUE,
    ADD COLUMN IF NOT EXISTS portal_reports_open BOOLEAN DEFAULT TRUE;
