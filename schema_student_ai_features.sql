-- Student Study AI persistence schema
-- Run in Supabase SQL editor

CREATE TABLE IF NOT EXISTS student_ai_chat_history (
    id BIGSERIAL PRIMARY KEY,
    school_id INTEGER,
    student_type VARCHAR(20) NOT NULL,
    student_id INTEGER NOT NULL,
    user_id INTEGER,
    classroom_id INTEGER,
    task VARCHAR(40) NOT NULL,
    prompt TEXT,
    response_text TEXT,
    response_mode VARCHAR(40),
    used_context JSONB,
    has_image BOOLEAN DEFAULT FALSE,
    image_name VARCHAR(255),
    created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_student_ai_chat_history_student ON student_ai_chat_history(student_type, student_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_student_ai_chat_history_classroom ON student_ai_chat_history(classroom_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_student_ai_chat_history_has_image ON student_ai_chat_history(student_type, student_id, has_image, created_at DESC);

CREATE TABLE IF NOT EXISTS student_ai_weekly_quizzes (
    id BIGSERIAL PRIMARY KEY,
    school_id INTEGER,
    student_type VARCHAR(20) NOT NULL,
    student_id INTEGER NOT NULL,
    user_id INTEGER,
    classroom_id INTEGER,
    week_key VARCHAR(16) NOT NULL,
    quiz_payload JSONB NOT NULL,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_student_ai_weekly_quizzes_student_week ON student_ai_weekly_quizzes(student_type, student_id, week_key, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_student_ai_weekly_quizzes_classroom_week ON student_ai_weekly_quizzes(classroom_id, week_key, created_at DESC);

CREATE TABLE IF NOT EXISTS student_ai_quiz_attempts (
    id BIGSERIAL PRIMARY KEY,
    school_id INTEGER,
    student_type VARCHAR(20) NOT NULL,
    student_id INTEGER NOT NULL,
    user_id INTEGER,
    weekly_quiz_id BIGINT,
    classroom_id INTEGER,
    score INTEGER NOT NULL,
    total_questions INTEGER NOT NULL,
    answers_payload JSONB,
    feedback TEXT,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_student_ai_quiz_attempts_student ON student_ai_quiz_attempts(student_type, student_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_student_ai_quiz_attempts_weekly_quiz ON student_ai_quiz_attempts(weekly_quiz_id, created_at DESC);
