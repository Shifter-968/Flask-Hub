-- =============================================================================
-- FLASK HUB — School Website Multi-Tenant Schema
-- Run this in your Supabase SQL Editor
-- Content tables use UUID primary keys, but school_id matches schools.id
-- which is currently INTEGER in this project
-- =============================================================================


-- =============================================================================
-- GROUP 1 — Extend existing schools table
-- (Only adding columns that don't already exist)
-- =============================================================================

ALTER TABLE schools
    ADD COLUMN IF NOT EXISTS primary_color     VARCHAR(7)   DEFAULT '#1d4ed8',
    ADD COLUMN IF NOT EXISTS accent_color      VARCHAR(7)   DEFAULT '#0f172a',
    ADD COLUMN IF NOT EXISTS layout_template   VARCHAR(80),
    ADD COLUMN IF NOT EXISTS custom_css        TEXT,
    ADD COLUMN IF NOT EXISTS logo_url          TEXT,
    ADD COLUMN IF NOT EXISTS hero_image_url    TEXT,
    ADD COLUMN IF NOT EXISTS motto             TEXT,
    ADD COLUMN IF NOT EXISTS tagline           TEXT,
    ADD COLUMN IF NOT EXISTS established_year  INTEGER,
    ADD COLUMN IF NOT EXISTS accreditation     TEXT,
    ADD COLUMN IF NOT EXISTS is_active         BOOLEAN      DEFAULT TRUE;


-- =============================================================================
-- GROUP 2 — Navigation
-- =============================================================================

CREATE TABLE IF NOT EXISTS school_menu (
    id             UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
    school_id      INTEGER     NOT NULL REFERENCES schools(id) ON DELETE CASCADE,
    label          VARCHAR(60) NOT NULL,
    slug           VARCHAR(60) NOT NULL,
    icon           VARCHAR(40),
    display_order  INTEGER     DEFAULT 0,
    is_external    BOOLEAN     DEFAULT FALSE,
    external_url   TEXT,
    is_active      BOOLEAN     DEFAULT TRUE,
    UNIQUE (school_id, slug)
);


-- =============================================================================
-- GROUP 3 — Pages & Sections
-- =============================================================================

CREATE TABLE IF NOT EXISTS school_pages (
    id                UUID         PRIMARY KEY DEFAULT gen_random_uuid(),
    school_id         INTEGER      NOT NULL REFERENCES schools(id) ON DELETE CASCADE,
    slug              VARCHAR(80)  NOT NULL,
    title             VARCHAR(200) NOT NULL,
    meta_description  TEXT,
    hero_image_url    TEXT,
    is_published      BOOLEAN      DEFAULT FALSE,
    created_at        TIMESTAMP    DEFAULT NOW(),
    updated_at        TIMESTAMP    DEFAULT NOW(),
    UNIQUE (school_id, slug)
);

CREATE TABLE IF NOT EXISTS school_sections (
    id             UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
    school_id      INTEGER     NOT NULL REFERENCES schools(id) ON DELETE CASCADE,
    page_id        UUID        NOT NULL REFERENCES school_pages(id) ON DELETE CASCADE,
    section_type   VARCHAR(40) NOT NULL,
    -- Allowed values: text_block, two_column, three_column, hero_banner,
    --                 cta_banner, gallery_grid, staff_grid, events_list,
    --                 news_feed, download_list, contact_map,
    --                 testimonial_carousel, faq_accordion, form_embed,
    --                 video_embed, audio_player, iframe_block
    heading        TEXT,
    body_html      TEXT,
    display_order  INTEGER  DEFAULT 0,
    is_visible     BOOLEAN  DEFAULT TRUE
);


-- =============================================================================
-- GROUP 4 — Media Library
-- =============================================================================

CREATE TABLE IF NOT EXISTS school_gallery_albums (
    id               UUID         PRIMARY KEY DEFAULT gen_random_uuid(),
    school_id        INTEGER      NOT NULL REFERENCES schools(id) ON DELETE CASCADE,
    title            VARCHAR(200) NOT NULL,
    description      TEXT,
    cover_image_url  TEXT,
    category         VARCHAR(30),
    -- Allowed values: photos, videos, events, achievements
    is_published     BOOLEAN  DEFAULT FALSE,
    display_order    INTEGER  DEFAULT 0
);

CREATE TABLE IF NOT EXISTS school_media (
    id               UUID         PRIMARY KEY DEFAULT gen_random_uuid(),
    school_id        INTEGER      NOT NULL REFERENCES schools(id) ON DELETE CASCADE,
    album_id         UUID         REFERENCES school_gallery_albums(id) ON DELETE SET NULL,
    page_id          UUID         REFERENCES school_pages(id) ON DELETE SET NULL,
    media_type       VARCHAR(20)  NOT NULL,
    -- Allowed values: image, video_upload, video_embed, audio,
    --                 document_pdf, document_word, document_excel, svg, iframe
    file_url         TEXT,
    thumbnail_url    TEXT,
    embed_code       TEXT,
    alt_text         VARCHAR(200),
    caption          TEXT,
    file_name        VARCHAR(200),
    file_size_kb     INTEGER,
    mime_type        VARCHAR(80),
    duration_seconds INTEGER,
    display_order    INTEGER  DEFAULT 0,
    created_at       TIMESTAMP DEFAULT NOW()
);


-- =============================================================================
-- GROUP 5 — Staff Directory
-- =============================================================================

CREATE TABLE IF NOT EXISTS school_staff (
    id              UUID         PRIMARY KEY DEFAULT gen_random_uuid(),
    school_id       INTEGER      NOT NULL REFERENCES schools(id) ON DELETE CASCADE,
    full_name       VARCHAR(150) NOT NULL,
    title           VARCHAR(40),
    role            VARCHAR(100),
    department      VARCHAR(100),
    bio             TEXT,
    photo_url       TEXT,
    email           VARCHAR(150),
    phone           VARCHAR(80),
    qualifications  TEXT,
    display_order   INTEGER  DEFAULT 0,
    is_active       BOOLEAN  DEFAULT TRUE
);


-- =============================================================================
-- GROUP 6 — News & Events
-- =============================================================================

CREATE TABLE IF NOT EXISTS school_news (
    id               UUID         PRIMARY KEY DEFAULT gen_random_uuid(),
    school_id        INTEGER      NOT NULL REFERENCES schools(id) ON DELETE CASCADE,
    title            VARCHAR(250) NOT NULL,
    slug             VARCHAR(250) NOT NULL,
    excerpt          TEXT,
    body_html        TEXT,
    cover_image_url  TEXT,
    category         VARCHAR(60),
    -- Allowed values: academic, sports, notice, event
    author_name      VARCHAR(150),
    published_at     TIMESTAMP,
    is_published     BOOLEAN  DEFAULT FALSE,
    is_featured      BOOLEAN  DEFAULT FALSE,
    view_count       INTEGER  DEFAULT 0,
    UNIQUE (school_id, slug)
);

CREATE TABLE IF NOT EXISTS school_events (
    id            UUID         PRIMARY KEY DEFAULT gen_random_uuid(),
    school_id     INTEGER      NOT NULL REFERENCES schools(id) ON DELETE CASCADE,
    title         VARCHAR(250) NOT NULL,
    description   TEXT,
    event_date    DATE         NOT NULL,
    end_date      DATE,
    event_type    VARCHAR(40),
    -- Allowed values: academic, sports, cultural, exam, holiday
    venue         VARCHAR(200),
    image_url     TEXT,
    is_published  BOOLEAN  DEFAULT FALSE,
    is_featured   BOOLEAN  DEFAULT FALSE
);


-- =============================================================================
-- GROUP 7 — Achievements & Testimonials
-- =============================================================================

CREATE TABLE IF NOT EXISTS school_achievements (
    id                UUID         PRIMARY KEY DEFAULT gen_random_uuid(),
    school_id         INTEGER      NOT NULL REFERENCES schools(id) ON DELETE CASCADE,
    title             VARCHAR(250) NOT NULL,
    description       TEXT,
    achievement_date  DATE,
    category          VARCHAR(60),
    -- Allowed values: academic, sports, arts, community
    awarding_body     VARCHAR(150),
    image_url         TEXT,
    is_featured       BOOLEAN  DEFAULT FALSE
);

CREATE TABLE IF NOT EXISTS school_testimonials (
    id                UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
    school_id         INTEGER     NOT NULL REFERENCES schools(id) ON DELETE CASCADE,
    quote             TEXT        NOT NULL,
    author_name       VARCHAR(150) NOT NULL,
    author_role       VARCHAR(100),
    author_photo_url  TEXT,
    rating            SMALLINT    CHECK (rating BETWEEN 1 AND 5),
    is_featured       BOOLEAN  DEFAULT FALSE,
    display_order     INTEGER  DEFAULT 0
);


-- =============================================================================
-- GROUP 8 — Downloads & FAQs
-- =============================================================================

CREATE TABLE IF NOT EXISTS school_downloads (
    id               UUID         PRIMARY KEY DEFAULT gen_random_uuid(),
    school_id        INTEGER      NOT NULL REFERENCES schools(id) ON DELETE CASCADE,
    label            VARCHAR(200) NOT NULL,
    description      TEXT,
    file_url         TEXT         NOT NULL,
    file_type        VARCHAR(20),
    -- Allowed values: pdf, docx, xlsx, zip
    file_size_kb     INTEGER,
    category         VARCHAR(60),
    -- Allowed values: prospectus, forms, policies, timetables, reports
    download_count   INTEGER  DEFAULT 0,
    is_active        BOOLEAN  DEFAULT TRUE
);

CREATE TABLE IF NOT EXISTS school_faqs (
    id            UUID  PRIMARY KEY DEFAULT gen_random_uuid(),
    school_id     INTEGER NOT NULL REFERENCES schools(id) ON DELETE CASCADE,
    question      TEXT  NOT NULL,
    answer        TEXT  NOT NULL,
    category      VARCHAR(60),
    -- Allowed values: admissions, fees, general, academic
    display_order INTEGER DEFAULT 0,
    is_published  BOOLEAN DEFAULT TRUE
);


-- =============================================================================
-- GROUP 9 — Dynamic Application / Enrollment Forms
-- =============================================================================

CREATE TABLE IF NOT EXISTS school_forms (
    id                  UUID         PRIMARY KEY DEFAULT gen_random_uuid(),
    school_id           INTEGER      NOT NULL REFERENCES schools(id) ON DELETE CASCADE,
    form_name           VARCHAR(200) NOT NULL,
    form_slug           VARCHAR(80)  NOT NULL,
    description         TEXT,
    submissions_email   VARCHAR(150),
    is_active           BOOLEAN   DEFAULT TRUE,
    closes_at           TIMESTAMP,
    UNIQUE (school_id, form_slug)
);

CREATE TABLE IF NOT EXISTS school_form_fields (
    id             UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
    form_id        UUID        NOT NULL REFERENCES school_forms(id) ON DELETE CASCADE,
    field_label    VARCHAR(150) NOT NULL,
    field_type     VARCHAR(30)  NOT NULL,
    -- Allowed values: text, email, phone, number, date, textarea,
    --                 select, radio, checkbox, file_upload, heading, divider
    placeholder    VARCHAR(150),
    options_json   JSONB,
    -- For select/radio/checkbox: ["Option A", "Option B"]
    is_required    BOOLEAN  DEFAULT FALSE,
    display_order  INTEGER  DEFAULT 0
);

CREATE TABLE IF NOT EXISTS school_form_submissions (
    id            UUID       PRIMARY KEY DEFAULT gen_random_uuid(),
    form_id       UUID       NOT NULL REFERENCES school_forms(id) ON DELETE CASCADE,
    school_id     INTEGER    NOT NULL REFERENCES schools(id) ON DELETE CASCADE,
    data_json     JSONB      NOT NULL,
    -- Stores all field responses: {"field_uuid": "value", ...}
    submitted_at  TIMESTAMP  DEFAULT NOW(),
    ip_hash       VARCHAR(64)
    -- Stores SHA-256 hash of submitter IP, never the raw IP address
);


-- =============================================================================
-- GROUP 10 — Contact Info & Social Links
-- =============================================================================

CREATE TABLE IF NOT EXISTS school_contact_info (
    id                UUID         PRIMARY KEY DEFAULT gen_random_uuid(),
    school_id         INTEGER      NOT NULL REFERENCES schools(id) ON DELETE CASCADE,
    address_line1     VARCHAR(200),
    address_line2     VARCHAR(200),
    city              VARCHAR(100),
    country           VARCHAR(100),
    postal_code       VARCHAR(20),
    phone_primary     VARCHAR(80),
    phone_secondary   VARCHAR(80),
    email_primary     VARCHAR(150),
    email_secondary   VARCHAR(150),
    maps_embed_url    TEXT,
    coordinates_lat   DECIMAL(9,6),
    coordinates_lng   DECIMAL(9,6),
    UNIQUE (school_id)
);

CREATE TABLE IF NOT EXISTS school_social_links (
    id             UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
    school_id      INTEGER     NOT NULL REFERENCES schools(id) ON DELETE CASCADE,
    platform       VARCHAR(30) NOT NULL,
    -- Allowed values: facebook, instagram, twitter, youtube,
    --                 linkedin, tiktok, whatsapp
    url            TEXT        NOT NULL,
    display_order  INTEGER     DEFAULT 0
);


-- =============================================================================
-- GROUP 11 — Announcements (Banners, Popups, Notices)
-- =============================================================================

CREATE TABLE IF NOT EXISTS school_announcements (
    id                  UUID         PRIMARY KEY DEFAULT gen_random_uuid(),
    school_id           INTEGER      NOT NULL REFERENCES schools(id) ON DELETE CASCADE,
    title               VARCHAR(200) NOT NULL,
    body                TEXT,
    announcement_type   VARCHAR(20)  DEFAULT 'notice',
    -- Allowed values: banner, popup, notice, alert
    starts_at           TIMESTAMP,
    expires_at          TIMESTAMP,
    is_active           BOOLEAN  DEFAULT TRUE
);


-- =============================================================================
-- INDEXES — Speed up common lookups by school_id and slug
-- =============================================================================

CREATE INDEX IF NOT EXISTS idx_school_menu_school        ON school_menu(school_id);
CREATE INDEX IF NOT EXISTS idx_school_pages_school       ON school_pages(school_id);
CREATE INDEX IF NOT EXISTS idx_school_pages_slug         ON school_pages(school_id, slug);
CREATE INDEX IF NOT EXISTS idx_school_sections_page      ON school_sections(page_id);
CREATE INDEX IF NOT EXISTS idx_school_media_school       ON school_media(school_id);
CREATE INDEX IF NOT EXISTS idx_school_media_album        ON school_media(album_id);
CREATE INDEX IF NOT EXISTS idx_school_staff_school       ON school_staff(school_id);
CREATE INDEX IF NOT EXISTS idx_school_news_school        ON school_news(school_id);
CREATE INDEX IF NOT EXISTS idx_school_news_published     ON school_news(school_id, is_published);
CREATE INDEX IF NOT EXISTS idx_school_events_school      ON school_events(school_id);
CREATE INDEX IF NOT EXISTS idx_school_events_date        ON school_events(event_date);
CREATE INDEX IF NOT EXISTS idx_school_achievements       ON school_achievements(school_id);
CREATE INDEX IF NOT EXISTS idx_school_testimonials       ON school_testimonials(school_id);
CREATE INDEX IF NOT EXISTS idx_school_downloads          ON school_downloads(school_id);
CREATE INDEX IF NOT EXISTS idx_school_faqs               ON school_faqs(school_id);
CREATE INDEX IF NOT EXISTS idx_school_forms_school       ON school_forms(school_id);
CREATE INDEX IF NOT EXISTS idx_school_form_fields_form   ON school_form_fields(form_id);
CREATE INDEX IF NOT EXISTS idx_school_submissions_form   ON school_form_submissions(form_id);
CREATE INDEX IF NOT EXISTS idx_school_contact            ON school_contact_info(school_id);
CREATE INDEX IF NOT EXISTS idx_school_social             ON school_social_links(school_id);
CREATE INDEX IF NOT EXISTS idx_school_announcements      ON school_announcements(school_id);

-- =============================================================================
-- END OF SCHEMA
-- =============================================================================
