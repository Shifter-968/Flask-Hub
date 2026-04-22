-- =============================================================================
-- Seed content for Limkokwing University into dynamic school-site tables
-- Purpose: Premium tertiary site (black/white base + accent communication colors)
-- =============================================================================

-- Ensure per-school CSS column exists
ALTER TABLE schools ADD COLUMN IF NOT EXISTS custom_css TEXT;
ALTER TABLE schools ADD COLUMN IF NOT EXISTS layout_template VARCHAR(80);

-- Ensure Limkokwing school exists
INSERT INTO schools (name, school_type, location, logo, contact_number, contact_email)
SELECT
  'Limkokwing University',
  'tertiary',
  'Mbabane, Eswatini',
  'https://dummyimage.com/220x220/111111/ffffff.png&text=LU',
  '+268 2400 1111',
  'admissions@limkokwing.edu.sz'
WHERE NOT EXISTS (
  SELECT 1 FROM schools WHERE lower(name) LIKE '%limkokwing%'
);

-- 1) Resolve school id and set Limkokwing brand profile
WITH sid AS (
  SELECT id
  FROM schools
  WHERE lower(name) LIKE '%limkokwing%'
  ORDER BY id
  LIMIT 1
)
UPDATE schools s
SET
  tagline = 'Global Creative University | Innovation, Design, Technology',
  motto = 'Where Creativity Meets Technology',
  primary_color = '#111111',
  accent_color = '#f59e0b',
  logo_url = 'https://dummyimage.com/220x220/111111/ffffff.png&text=LU',
  hero_image_url = 'https://dummyimage.com/1600x900/1f2937/f3f4f6.png&text=Limkokwing+University',
  accreditation = 'Accredited Higher Education Institution',
  established_year = 1991,
  is_active = TRUE,
  layout_template = 'premium_university_v2',
  custom_css = '.site-nav{background:#0b0b0d}.menu a.active{color:#22d3ee}.menu a.apply-link{background:#14b8a6}.hero{background:linear-gradient(145deg,#0f1115,#1f2937)}.section{background:rgba(255,255,255,0.82);backdrop-filter:blur(10px)}.count-card{border-left-color:#22d3ee}.site-footer{background:linear-gradient(180deg,#0b0b0d,#171717)} body{background:radial-gradient(900px 480px at 0% 0%,rgba(34,211,238,.08),transparent 50%),radial-gradient(900px 480px at 100% 100%,rgba(20,184,166,.10),transparent 50%),#f3f4f6}'
FROM sid
WHERE s.id = sid.id;

-- 2) Clear old dynamic content for Limkokwing (idempotent)
WITH sid AS (SELECT id FROM schools WHERE lower(name) LIKE '%limkokwing%' ORDER BY id LIMIT 1)
DELETE FROM school_menu WHERE school_id IN (SELECT id FROM sid);

WITH sid AS (SELECT id FROM schools WHERE lower(name) LIKE '%limkokwing%' ORDER BY id LIMIT 1)
DELETE FROM school_sections WHERE school_id IN (SELECT id FROM sid);

WITH sid AS (SELECT id FROM schools WHERE lower(name) LIKE '%limkokwing%' ORDER BY id LIMIT 1)
DELETE FROM school_pages WHERE school_id IN (SELECT id FROM sid);

WITH sid AS (SELECT id FROM schools WHERE lower(name) LIKE '%limkokwing%' ORDER BY id LIMIT 1)
DELETE FROM school_staff WHERE school_id IN (SELECT id FROM sid);

WITH sid AS (SELECT id FROM schools WHERE lower(name) LIKE '%limkokwing%' ORDER BY id LIMIT 1)
DELETE FROM school_gallery_albums WHERE school_id IN (SELECT id FROM sid);

WITH sid AS (SELECT id FROM schools WHERE lower(name) LIKE '%limkokwing%' ORDER BY id LIMIT 1)
DELETE FROM school_news WHERE school_id IN (SELECT id FROM sid);

WITH sid AS (SELECT id FROM schools WHERE lower(name) LIKE '%limkokwing%' ORDER BY id LIMIT 1)
DELETE FROM school_events WHERE school_id IN (SELECT id FROM sid);

WITH sid AS (SELECT id FROM schools WHERE lower(name) LIKE '%limkokwing%' ORDER BY id LIMIT 1)
DELETE FROM school_testimonials WHERE school_id IN (SELECT id FROM sid);

WITH sid AS (SELECT id FROM schools WHERE lower(name) LIKE '%limkokwing%' ORDER BY id LIMIT 1)
DELETE FROM school_downloads WHERE school_id IN (SELECT id FROM sid);

WITH sid AS (SELECT id FROM schools WHERE lower(name) LIKE '%limkokwing%' ORDER BY id LIMIT 1)
DELETE FROM school_contact_info WHERE school_id IN (SELECT id FROM sid);

WITH sid AS (SELECT id FROM schools WHERE lower(name) LIKE '%limkokwing%' ORDER BY id LIMIT 1)
DELETE FROM school_social_links WHERE school_id IN (SELECT id FROM sid);

WITH sid AS (SELECT id FROM schools WHERE lower(name) LIKE '%limkokwing%' ORDER BY id LIMIT 1)
DELETE FROM school_media WHERE school_id IN (SELECT id FROM sid);

-- 3) Navigation tabs for tertiary institution
WITH sid AS (SELECT id FROM schools WHERE lower(name) LIKE '%limkokwing%' ORDER BY id LIMIT 1)
INSERT INTO school_menu (school_id, label, slug, display_order, is_external, external_url, is_active)
SELECT sid.id, m.label, m.slug, m.display_order, m.is_external, m.external_url, TRUE
FROM sid,
(VALUES
  ('Home', 'home', 1, FALSE, NULL),
  ('About', 'about', 2, FALSE, NULL),
  ('Faculties', 'faculties', 3, FALSE, NULL),
  ('Admissions', 'admissions', 4, FALSE, NULL),
  ('International', 'international', 5, FALSE, NULL),
  ('News', 'news', 6, FALSE, NULL),
  ('Contact', 'contact', 7, FALSE, NULL),
  ('Apply Now', 'apply', 8, TRUE, 'https://apply.example.edu/limkokwing')
) AS m(label, slug, display_order, is_external, external_url);

-- 4) Pages
WITH sid AS (SELECT id FROM schools WHERE lower(name) LIKE '%limkokwing%' ORDER BY id LIMIT 1)
INSERT INTO school_pages (school_id, slug, title, meta_description, hero_image_url, is_published)
SELECT sid.id, p.slug, p.title, p.meta_description, p.hero_image_url, TRUE
FROM sid,
(VALUES
  ('home', 'Build The Future With Limkokwing', 'A world-class university focused on creative leadership, digital transformation, entrepreneurship, and future-ready learning.', 'https://dummyimage.com/1600x900/111827/e5e7eb.png&text=Future+Campus'),
  ('about', 'About Limkokwing University', 'We are a global creative university combining design, media, technology, and business for real-world impact.', 'https://dummyimage.com/1600x900/0f172a/e2e8f0.png&text=Global+Creative+University'),
  ('faculties', 'Faculties & Schools', 'Explore interdisciplinary faculties built for innovation and employability.', 'https://dummyimage.com/1600x900/1e293b/f1f5f9.png&text=Faculties'),
  ('admissions', 'Admissions', 'Start your application journey for undergraduate and postgraduate study.', 'https://dummyimage.com/1600x900/374151/f9fafb.png&text=Admissions'),
  ('international', 'International Students', 'Find pathways, visa support, accommodation guidance, and global exchange opportunities.', 'https://dummyimage.com/1600x900/0f172a/f8fafc.png&text=International+Office'),
  ('news', 'University News', 'Stay informed with updates on events, awards, partnerships, and thought leadership.', 'https://dummyimage.com/1600x900/111827/e5e7eb.png&text=Newsroom'),
  ('contact', 'Contact & Visit', 'Contact admissions, schedule a campus tour, or reach key university offices.', 'https://dummyimage.com/1600x900/0b1220/f1f5f9.png&text=Contact+Us')
) AS p(slug, title, meta_description, hero_image_url);

-- 5) Sections
WITH sid AS (
  SELECT id FROM schools WHERE lower(name) LIKE '%limkokwing%' ORDER BY id LIMIT 1
), pg AS (
  SELECT id, slug FROM school_pages WHERE school_id = (SELECT id FROM sid)
)
INSERT INTO school_sections (school_id, page_id, section_type, heading, body_html, display_order, is_visible)
SELECT (SELECT id FROM sid), pg.id, s.section_type, s.heading, s.body_html, s.display_order, TRUE
FROM pg
JOIN (
  VALUES
  ('home', 'text_block', 'Why Limkokwing?', '<p><strong>Future-ready programmes:</strong> Design, media, IT, business, architecture, and innovation.</p><p><strong>Global orientation:</strong> International exposure and culturally diverse learning communities.</p><p><strong>Industry-linked teaching:</strong> Capstone projects, internships, and practical studio-based training.</p>', 1),
  ('home', 'text_block', 'Signature Highlights', '<p>Top employability focus, startup incubation support, modern creative labs, and mentorship-led student development.</p>', 2),

  ('about', 'text_block', 'Our Story', '<p>Limkokwing University is built on the conviction that creative thinking and technological fluency are the strongest engines of progress.</p><p>We deliver interdisciplinary education where students learn to solve real problems, launch ideas, and lead transformation in the digital economy.</p>', 1),
  ('about', 'text_block', 'Our Mission & Vision', '<p><strong>Mission:</strong> To develop globally competent graduates who combine creativity, strategy, and ethical leadership.</p><p><strong>Vision:</strong> To be a leading global institution for creative innovation and future-focused education.</p>', 2),

  ('faculties', 'text_block', 'Academic Faculties', '<ul><li>Faculty of Creative Multimedia</li><li>Faculty of Business & Global Management</li><li>Faculty of Information Technology</li><li>Faculty of Communication & Media Studies</li><li>Faculty of Architecture & Built Environment</li><li>School of Postgraduate Studies</li></ul>', 1),
  ('faculties', 'text_block', 'Popular Programmes', '<p>Diploma and Degree pathways in Graphic Design, Animation, UX/UI, Software Engineering, Digital Marketing, Film Production, and Entrepreneurial Leadership.</p>', 2),

  ('admissions', 'text_block', 'Admissions Process', '<ol><li><strong>Apply Online:</strong> Complete the digital application form.</li><li><strong>Submit Documents:</strong> Academic transcripts, ID/Passport, and supporting records.</li><li><strong>Offer & Registration:</strong> Receive offer letter, pay deposit, and register.</li></ol>', 1),
  ('admissions', 'download_list', 'Prospectus & Fee Guide', '<p>Download programme information, admission requirements, tuition and payment guidance.</p>', 2),

  ('international', 'text_block', 'International Office', '<p>We support applicants with visa guidance, pre-arrival support, accommodation referrals, orientation, and cultural integration.</p>', 1),
  ('international', 'text_block', 'Global Pathways', '<p>Exchange opportunities, international collaborations, and cross-border project work.</p>', 2),

  ('news', 'news_feed', 'Latest University News', '<p>Read stories about achievements, events, partnerships, and thought leadership.</p>', 1),
  ('news', 'events_list', 'Upcoming University Events', '<p>Stay updated with open days, public lectures, and career fairs.</p>', 2),

  ('contact', 'contact_map', 'Contact & Visit', '<p>Connect with admissions, faculties, and student support. Schedule a campus tour.</p>', 1),
  ('contact', 'download_list', 'Important Documents', '<p>Forms, handbook, policy documents, and enrollment resources.</p>', 2)
) AS s(page_slug, section_type, heading, body_html, display_order)
ON pg.slug = s.page_slug;

-- 6) Leadership and staff
WITH sid AS (SELECT id FROM schools WHERE lower(name) LIKE '%limkokwing%' ORDER BY id LIMIT 1)
INSERT INTO school_staff (school_id, full_name, role, department, photo_url, display_order, is_active)
SELECT sid.id, x.full_name, x.role, x.department, x.photo_url, x.display_order, TRUE
FROM sid,
(VALUES
  ('Prof. T. Maseko', 'Vice Chancellor', 'Office of the Vice Chancellor', 'https://dummyimage.com/640x800/111111/f5f5f5.png&text=Vice+Chancellor', 1),
  ('Dr. N. Dlamini', 'Deputy Vice Chancellor', 'Academic Affairs', 'https://dummyimage.com/640x800/1f2937/f9fafb.png&text=Deputy+VC', 2),
  ('Ms. P. Khumalo', 'Registrar', 'Registry Services', 'https://dummyimage.com/640x800/0f172a/f1f5f9.png&text=Registrar', 3),
  ('Mr. A. Moyo', 'Director', 'Student Affairs', 'https://dummyimage.com/640x800/1e293b/f8fafc.png&text=Student+Affairs', 4)
) AS x(full_name, role, department, photo_url, display_order);

-- 7) Student life gallery albums
WITH sid AS (SELECT id FROM schools WHERE lower(name) LIKE '%limkokwing%' ORDER BY id LIMIT 1)
INSERT INTO school_gallery_albums (school_id, title, description, cover_image_url, category, is_published, display_order)
SELECT sid.id, a.title, a.description, a.cover_image_url, a.category, TRUE, a.display_order
FROM sid,
(VALUES
  ('Creative Labs', 'Digital studios, media rooms, and design labs.', 'https://dummyimage.com/1200x800/111827/e5e7eb.png&text=Creative+Labs', 'photos', 1),
  ('Student Clubs', 'Leadership, entrepreneurship, and cultural clubs.', 'https://dummyimage.com/1200x800/1f2937/f9fafb.png&text=Student+Clubs', 'events', 2),
  ('Innovation Expo', 'Annual showcase of student projects and startups.', 'https://dummyimage.com/1200x800/0f172a/f8fafc.png&text=Innovation+Expo', 'events', 3),
  ('Graduation', 'Celebrating graduate success and future pathways.', 'https://dummyimage.com/1200x800/111111/ffffff.png&text=Graduation', 'achievements', 4)
) AS a(title, description, cover_image_url, category, display_order);

-- 8) News
WITH sid AS (SELECT id FROM schools WHERE lower(name) LIKE '%limkokwing%' ORDER BY id LIMIT 1)
INSERT INTO school_news (school_id, title, slug, excerpt, body_html, cover_image_url, category, author_name, published_at, is_published, is_featured, view_count)
SELECT sid.id, n.title, n.slug, n.excerpt, n.body_html, n.cover_image_url, n.category, 'University Communications', n.published_at::timestamp, TRUE, n.is_featured, 0
FROM sid,
(VALUES
  ('Limkokwing Launches AI Design Lab', 'ai-design-lab-launch', 'A new interdisciplinary lab connecting AI, design, and product innovation.', '<p>The university has launched a state-of-the-art AI Design Lab to support interdisciplinary projects in machine creativity, UX, and digital product innovation.</p>', 'https://dummyimage.com/1200x800/111827/e5e7eb.png&text=AI+Design+Lab', 'innovation', '2026-04-01 10:00:00', TRUE),
  ('Industry Career Fair 2026 Announced', 'career-fair-2026', 'Employers, startups, and graduate schools join the annual career fair.', '<p>The annual Career Fair connects students with regional and international employers, internship opportunities, and postgraduate pathways.</p>', 'https://dummyimage.com/1200x800/1f2937/f9fafb.png&text=Career+Fair', 'careers', '2026-03-28 09:00:00', FALSE),
  ('Global Media Festival Week', 'global-media-festival-week', 'A week of exhibitions, screenings, and creative workshops.', '<p>Students and invited professionals collaborate through masterclasses, screenings, and production showcases during Media Festival Week.</p>', 'https://dummyimage.com/1200x800/0f172a/f1f5f9.png&text=Media+Festival', 'culture', '2026-03-22 12:00:00', FALSE)
) AS n(title, slug, excerpt, body_html, cover_image_url, category, published_at, is_featured);

-- 9) Events
WITH sid AS (SELECT id FROM schools WHERE lower(name) LIKE '%limkokwing%' ORDER BY id LIMIT 1)
INSERT INTO school_events (school_id, title, description, event_date, end_date, event_type, venue, image_url, is_published, is_featured)
SELECT sid.id, e.title, e.description, e.event_date::date, NULL::date, e.event_type, e.venue, NULL, TRUE, e.is_featured
FROM sid,
(VALUES
  ('Open Day & Campus Tours', 'Meet faculty, tour labs, and explore programs.', '2026-05-04', 'academic', 'Main Campus', TRUE),
  ('University Research Colloquium', 'Faculty and postgraduate research presentations.', '2026-05-18', 'academic', 'Innovation Auditorium', FALSE),
  ('Startup Pitch Night', 'Student founders pitch to mentors and investors.', '2026-06-10', 'cultural', 'Entrepreneurship Hub', FALSE),
  ('International Students Orientation', 'Welcome programme for incoming international students.', '2026-07-01', 'academic', 'International Office', FALSE)
) AS e(title, description, event_date, event_type, venue, is_featured);

-- 10) Testimonials
WITH sid AS (SELECT id FROM schools WHERE lower(name) LIKE '%limkokwing%' ORDER BY id LIMIT 1)
INSERT INTO school_testimonials (school_id, quote, author_name, author_role, author_photo_url, rating, is_featured, display_order)
SELECT sid.id, t.quote, t.author_name, t.author_role, t.author_photo_url, t.rating, TRUE, t.display_order
FROM sid,
(VALUES
  ('The project-based approach transformed how I solve problems. I graduated with a portfolio and real startup experience.', 'L. Ndlovu', 'Alumni | Digital Product Design', 'https://dummyimage.com/400x400/111111/f8fafc.png&text=Alumni', 5, 1),
  ('As an international student, support services made transition smooth and the learning environment truly global.', 'A. Mensah', 'International Student | Business Innovation', 'https://dummyimage.com/400x400/1f2937/f9fafb.png&text=Student', 5, 2)
) AS t(quote, author_name, author_role, author_photo_url, rating, display_order);

-- 11) Downloads
WITH sid AS (SELECT id FROM schools WHERE lower(name) LIKE '%limkokwing%' ORDER BY id LIMIT 1)
INSERT INTO school_downloads (school_id, label, description, file_url, file_type, file_size_kb, category, download_count, is_active)
SELECT sid.id, d.label, d.description, d.file_url, d.file_type, NULL, d.category, 0, TRUE
FROM sid,
(VALUES
  ('2026/27 Undergraduate Prospectus', 'Programmes, requirements, and pathways.', 'https://dummyimage.com/1000x1400/111827/e5e7eb.png&text=Undergraduate+Prospectus', 'pdf', 'prospectus'),
  ('Fee Structure Guide', 'Tuition, payment schedule, and financial information.', 'https://dummyimage.com/1000x1400/1f2937/f9fafb.png&text=Fee+Guide', 'pdf', 'forms'),
  ('International Admissions Pack', 'Visa, accommodation, and onboarding checklist.', 'https://dummyimage.com/1000x1400/0f172a/f8fafc.png&text=International+Pack', 'pdf', 'forms'),
  ('Student Handbook', 'Policies, conduct, and student services.', 'https://dummyimage.com/1000x1400/111111/ffffff.png&text=Student+Handbook', 'pdf', 'policies')
) AS d(label, description, file_url, file_type, category);

-- 12) Contact info
WITH sid AS (SELECT id FROM schools WHERE lower(name) LIKE '%limkokwing%' ORDER BY id LIMIT 1)
INSERT INTO school_contact_info (
  school_id, address_line1, address_line2, city, country, postal_code,
  phone_primary, phone_secondary, email_primary, email_secondary, maps_embed_url,
  coordinates_lat, coordinates_lng
)
SELECT
  sid.id,
  'Innovation Avenue',
  'University City Campus',
  'Mbabane',
  'Eswatini',
  'H100',
  '+268 2400 1111',
  '+268 2400 2222',
  'admissions@limkokwing.edu.sz',
  'info@limkokwing.edu.sz',
  'https://www.google.com/maps?q=Mbabane,+Eswatini&output=embed',
  -26.3167,
  31.1333
FROM sid;

-- 13) Social links
WITH sid AS (SELECT id FROM schools WHERE lower(name) LIKE '%limkokwing%' ORDER BY id LIMIT 1)
INSERT INTO school_social_links (school_id, platform, url, display_order)
SELECT sid.id, s.platform, s.url, s.display_order
FROM sid,
(VALUES
  ('facebook', 'https://www.facebook.com/', 1),
  ('instagram', 'https://www.instagram.com/', 2),
  ('linkedin', 'https://www.linkedin.com/', 3),
  ('youtube', 'https://www.youtube.com/', 4)
) AS s(platform, url, display_order);

-- 14) Page media
WITH sid AS (
  SELECT id FROM schools WHERE lower(name) LIKE '%limkokwing%' ORDER BY id LIMIT 1
), pg AS (
  SELECT id, slug FROM school_pages WHERE school_id = (SELECT id FROM sid)
)
INSERT INTO school_media (school_id, page_id, media_type, file_url, alt_text, caption, file_name, mime_type, display_order)
SELECT (SELECT id FROM sid), pg.id, m.media_type, m.file_url, m.alt_text, m.caption, m.file_name, m.mime_type, m.display_order
FROM pg
JOIN (
  VALUES
  ('home', 'image', 'https://dummyimage.com/1200x800/111827/e5e7eb.png&text=Creative+Hub', 'Creative hub', 'Creative Hub', 'creative-hub.png', 'image/png', 1),
  ('home', 'image', 'https://dummyimage.com/1200x800/1f2937/f8fafc.png&text=Digital+Studio', 'Digital studio', 'Digital Studio', 'digital-studio.png', 'image/png', 2),
  ('faculties', 'image', 'https://dummyimage.com/1200x800/0f172a/f1f5f9.png&text=Faculty+Spaces', 'Faculty spaces', 'Faculty Spaces', 'faculty-spaces.png', 'image/png', 1),
  ('admissions', 'image', 'https://dummyimage.com/1200x800/111111/ffffff.png&text=Admissions+Desk', 'Admissions desk', 'Admissions Desk', 'admissions-desk.png', 'image/png', 1),
  ('international', 'image', 'https://dummyimage.com/1200x800/1e293b/f9fafb.png&text=International+Office', 'International office', 'International Office', 'international-office.png', 'image/png', 1),
  ('news', 'image', 'https://dummyimage.com/1200x800/111827/e5e7eb.png&text=University+News', 'University news', 'University News', 'university-news.png', 'image/png', 1)
) AS m(page_slug, media_type, file_url, alt_text, caption, file_name, mime_type, display_order)
ON pg.slug = m.page_slug;

-- =============================================================================
-- END
-- =============================================================================
