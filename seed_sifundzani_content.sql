-- =============================================================================
-- Seed content for Sifundzani High School into dynamic school-site tables
-- Prerequisite: schema_school_website.sql already executed
-- =============================================================================

-- Ensure per-school CSS/template columns exist
ALTER TABLE schools ADD COLUMN IF NOT EXISTS custom_css TEXT;
ALTER TABLE schools ADD COLUMN IF NOT EXISTS layout_template VARCHAR(80);

-- Ensure Sifundzani school exists
INSERT INTO schools (name, school_type, location, logo, contact_number, contact_email)
SELECT
  'Sifundzani High School',
  'high_school',
  'Mbabane, Eswatini',
  'https://sifundzani.ac.sz/assets/icons/sifu-white.png?text=SHS',
  '(+268) 24041157',
  'info@sifundzani.ac.sz'
WHERE NOT EXISTS (
  SELECT 1 FROM schools WHERE lower(name) = lower('Sifundzani High School')
);

-- 1) Resolve school id and update branding fields
WITH sid AS (
  SELECT id FROM schools WHERE lower(name) = lower('Sifundzani High School') LIMIT 1
)
UPDATE schools s
SET
  tagline = 'Est. 1982 · Cambridge IGCSE, AS and A Levels',
  motto = 'Excellence in Education since 1982',
  primary_color = '#27469a',
  accent_color = '#ee2f3b',
  custom_css = '.hero{min-height:330px}.site-nav{background:#2f4a99}.count-card{border-top:4px solid #ee2f3b}',
  logo_url = 'https://sifundzani.ac.sz/assets/icons/sifu-white.png?text=SHS',
  hero_image_url = 'https://sifundzani.ac.sz/assets/images/system/hero.png',
  established_year = 1982,
  is_active = TRUE
FROM sid
WHERE s.id = sid.id;

-- 2) Clear old dynamic content for this school (idempotent reseed)
WITH sid AS (SELECT id FROM schools WHERE lower(name) = lower('Sifundzani High School') LIMIT 1)
DELETE FROM school_menu WHERE school_id IN (SELECT id FROM sid);

WITH sid AS (SELECT id FROM schools WHERE lower(name) = lower('Sifundzani High School') LIMIT 1)
DELETE FROM school_sections WHERE school_id IN (SELECT id FROM sid);

WITH sid AS (SELECT id FROM schools WHERE lower(name) = lower('Sifundzani High School') LIMIT 1)
DELETE FROM school_pages WHERE school_id IN (SELECT id FROM sid);

WITH sid AS (SELECT id FROM schools WHERE lower(name) = lower('Sifundzani High School') LIMIT 1)
DELETE FROM school_staff WHERE school_id IN (SELECT id FROM sid);

WITH sid AS (SELECT id FROM schools WHERE lower(name) = lower('Sifundzani High School') LIMIT 1)
DELETE FROM school_gallery_albums WHERE school_id IN (SELECT id FROM sid);

WITH sid AS (SELECT id FROM schools WHERE lower(name) = lower('Sifundzani High School') LIMIT 1)
DELETE FROM school_news WHERE school_id IN (SELECT id FROM sid);

WITH sid AS (SELECT id FROM schools WHERE lower(name) = lower('Sifundzani High School') LIMIT 1)
DELETE FROM school_events WHERE school_id IN (SELECT id FROM sid);

WITH sid AS (SELECT id FROM schools WHERE lower(name) = lower('Sifundzani High School') LIMIT 1)
DELETE FROM school_testimonials WHERE school_id IN (SELECT id FROM sid);

WITH sid AS (SELECT id FROM schools WHERE lower(name) = lower('Sifundzani High School') LIMIT 1)
DELETE FROM school_downloads WHERE school_id IN (SELECT id FROM sid);

WITH sid AS (SELECT id FROM schools WHERE lower(name) = lower('Sifundzani High School') LIMIT 1)
DELETE FROM school_contact_info WHERE school_id IN (SELECT id FROM sid);

WITH sid AS (SELECT id FROM schools WHERE lower(name) = lower('Sifundzani High School') LIMIT 1)
DELETE FROM school_social_links WHERE school_id IN (SELECT id FROM sid);

WITH sid AS (SELECT id FROM schools WHERE lower(name) = lower('Sifundzani High School') LIMIT 1)
DELETE FROM school_media WHERE school_id IN (SELECT id FROM sid);

-- 3) Navigation
WITH sid AS (SELECT id FROM schools WHERE lower(name) = lower('Sifundzani High School') LIMIT 1)
INSERT INTO school_menu (school_id, label, slug, display_order, is_external, external_url, is_active)
SELECT sid.id, x.label, x.slug, x.display_order, x.is_external, x.external_url, TRUE
FROM sid,
(VALUES
  ('Home', 'home', 1, FALSE, NULL),
  ('About', 'about', 2, FALSE, NULL),
  ('Academics', 'academics', 3, FALSE, NULL),
  ('Admissions', 'admissions', 4, FALSE, NULL),
  ('Staff', 'staff', 5, FALSE, NULL),
  ('Gallery', 'gallery', 6, FALSE, NULL),
  ('News', 'news', 7, FALSE, NULL),
  ('Contact', 'contact', 8, FALSE, NULL),
  ('Apply Now', 'apply', 9, TRUE, 'https://sifundzani.ed-space.net/onlineapplication.cfm')
) AS x(label, slug, display_order, is_external, external_url);

-- 4) Pages
WITH sid AS (SELECT id FROM schools WHERE lower(name) = lower('Sifundzani High School') LIMIT 1)
INSERT INTO school_pages (school_id, slug, title, meta_description, hero_image_url, is_published)
SELECT sid.id, p.slug, p.title, p.meta_description, p.hero_image_url, TRUE
FROM sid,
(VALUES
  ('home', 'Welcome to Sifundzani', 'The Sifundzani Community aims to foster the success of your child, by building strong relationships anchored in family-oriented beliefs.', 'https://sifundzani.ac.sz/assets/images/system/hero.png'),
  ('about', 'Our Story of Excellence', 'Rooted in Christian values, committed to academic rigour, and driven by innovation since 1982.', 'https://sifundzani.ac.sz/assets/images/system/hero.png'),
  ('academics', 'Academic Programs', 'Cambridge curriculum from Grade 1 through Form 5, preparing students for global success.', 'https://sifundzani.ac.sz/assets/images/system/classroom.png'),
  ('admissions', 'Admissions', 'Join our community of learners. Applications are now open.', 'https://sifundzani.ac.sz/assets/images/system/classroom.png'),
  ('staff', 'Our Leadership & Staff', 'Dedicated educators committed to nurturing each student''s potential.', 'https://sifundzani.ac.sz/assets/images/system/hero.png'),
  ('gallery', 'Campus Gallery', 'Explore our campus through themed albums.', 'https://sifundzani.ac.sz/assets/images/system/hero.png'),
  ('news', 'Latest News', 'Stay updated with events and achievements at Sifundzani.', 'https://sifundzani.ac.sz/assets/images/system/hero.png'),
  ('contact', 'Contact Us', 'We''d love to hear from you. Reach out with any questions or to schedule a campus tour.', 'https://sifundzani.ac.sz/assets/images/system/hero.png')
) AS p(slug, title, meta_description, hero_image_url);

-- 5) Sections per page
WITH sid AS (
  SELECT id FROM schools WHERE lower(name) = lower('Sifundzani High School') LIMIT 1
), pg AS (
  SELECT id, slug FROM school_pages WHERE school_id = (SELECT id FROM sid)
)
INSERT INTO school_sections (school_id, page_id, section_type, heading, body_html, display_order, is_visible)
SELECT (SELECT id FROM sid), pg.id, s.section_type, s.heading, s.body_html, s.display_order, TRUE
FROM pg
JOIN (
  VALUES
  ('home', 'text_block', 'Theme Statement', '<p>We strive to excel and meet this goal in line with our theme for the year of 2026: <strong>"Breaking New Grounds"</strong>.</p>', 1),
  ('home', 'two_column', 'About Our School', '<h3>Excellence in Education Since 1982</h3><p>Sifundzani High School is a registered K-12 institution offering Cambridge IGCSE curriculum from Grade 1 through Form 6. We are fully accredited by Cambridge International, ISASA and the Eswatini Ministry of Education and Training.</p><p><strong>Our Mission:</strong> Sifundzani is a Christian-based high school that provides quality education through innovation and leadership excellence.</p><p><strong>Our Vision:</strong> We seek to provide relevant learning opportunities that promote academic, physical, and emotional growth for our students to succeed in the 21st century.</p>', 2),
  ('home', 'cta_banner', 'Join The Sifundzani Community', '<p>Applications for the 2027 academic year are now open. Secure your child''s future today.</p>', 3),

  ('about', 'text_block', 'A Legacy of Excellence in Eswatini', '<p>Sifundzani was founded in 1982 with a simple yet powerful vision: to provide world-class education that nurtures both intellect and character. What began as a small community school has grown into one of Eswatini''s most respected Cambridge International institutions, serving students from Grade 1 through Form 6.</p><p>Over the past three decades, we have remained steadfast in our commitment to academic rigour, holistic development, and Christian-based values. Our accelerated IGCSE programme (completed in 4 years) gives students a competitive edge, allowing two full years for Cambridge AS and A Levels.</p>', 1),
  ('about', 'two_column', 'Mission & Vision', '<p><strong>Our Mission:</strong> Sifundzani is a Christian-based high school that provides quality education through innovation and leadership excellence to enable students to successfully compete globally.</p><p><strong>Our Vision:</strong> We seek to provide relevant learning opportunities that promote academic, physical, and emotional growth.</p>', 2),
  ('about', 'text_block', 'Our Core Values', '<p>The principles that guide everything we do at Sifundzani High School.</p><p><strong>Respect:</strong> We uphold respect for each other, as educators, for students, for parents, and all key stakeholders.</p><p><strong>Accountability:</strong> We strive to honour our commitments and comply with legislative and good practice standards.</p><p><strong>Teamwork:</strong> Through collaboration and empathy, we achieve more with our stakeholders.</p><p><strong>Professionalism:</strong> We are committed to quality education and the highest standards possible.</p><p><strong>Integrity:</strong> We commit to ethical, moral, honest, and transparent conduct at all times.</p>', 3),

  ('academics', 'text_block', 'Program Pathways', '<p><strong>Primary School:</strong> Grade 1-7, Cambridge Primary.</p><p><strong>Check Point:</strong> Form 1-2, Cambridge Lower Secondary.</p><p><strong>IGCSE:</strong> Form 3-4, Cambridge IGCSE.</p><p><strong>Sixth Form:</strong> Cambridge AS/A Levels.</p>', 1),
  ('academics', 'text_block', 'Subjects Offered (IGCSE)', '<p>English Language, Mathematics, Physics, Chemistry, Biology, Computer Science, Information and Communication Technology, Business Studies, Accounting, Economics, Geography, Environmental Management, History, French as a Second Language, Music, Art.</p><p><em>Subject availability may vary based on student demand and staffing.</em></p>', 2),
  ('academics', 'text_block', 'Form 3 Stream Choices', '<p>All students starting from Form 3 up until Form 4 will do 10 subjects, 9 of which are examination subjects. Out of the 9 examination subjects, 5 are compulsory and 4 are elected.</p><p><strong>Compulsory:</strong> English Language, English Literature, Mathematics, Religious Education, Second Language (SiSwati or French).</p><p>Students may select one subject per row across streams.</p>', 3),

  ('admissions', 'text_block', 'Admissions Process', '<ol><li><strong>Submit Application</strong> - Complete the online application and pay the non-refundable fee.</li><li><strong>Entrance Assessment</strong> - Students sit for English and Mathematics assessments.</li><li><strong>Interview & Offer</strong> - Successful candidates are invited for interview and offer.</li></ol>', 1),
  ('admissions', 'text_block', 'Why Sifundzani?', '<p><strong>Accelerated IGCSE Programme:</strong> Complete in 4 years instead of 5, giving your child two full years for advanced level studies.</p><p><strong>Three Exit Points:</strong> IGCSE (Year 4), AS (Year 5), A (Year 6), accepted worldwide.</p><p><strong>Highlights:</strong> Modern labs, sports excellence, resource centre, graduate success.</p><p><strong>Learning Path Strengths:</strong> 4-year IGCSE, 3 exit points, global recognition, A Level readiness.</p>', 2),
  ('admissions', 'download_list', 'Application Documents', '<p>Download detailed information about curriculum, admissions process and school life.</p>', 3),

  ('staff', 'staff_grid', 'Our Leadership & Staff', '<p>Dedicated educators committed to nurturing each student''s potential.</p>', 1),
  ('gallery', 'gallery_grid', 'Campus Gallery', '<p>Explore our campus through themed albums. Click on any album to view photos.</p>', 1),
  ('news', 'news_feed', 'Latest News', '<p>Stay updated with events and achievements at Sifundzani.</p>', 1),
  ('news', 'events_list', 'School Calendar', '<p>Important dates and events for the academic year.</p>', 2),
  ('news', 'testimonial_carousel', 'What Our Community Says', '<p>Hear from students and parents about their Sifundzani experience.</p>', 3),

  ('contact', 'contact_map', 'Contact Us', '<p>We''d love to hear from you. Reach out with any questions or to schedule a campus tour.</p>', 1),
  ('contact', 'download_list', 'School Policies', '<p>Guidelines that ensure a safe and productive learning environment.</p><p>Includes Social Media Policy, Academic Honesty Policy, Inclusion and Diversity Policy, and Anti-Bullying Policy.</p>', 2),
  ('contact', 'iframe_block', 'Follow Us on Facebook', '<p>Follow our official page: <a href="https://www.facebook.com/SifundzaniHighSchool" target="_blank" rel="noopener">Sifundzani High School</a>.</p>', 3),
  ('contact', 'text_block', 'Our Accreditation and Affiliations', '<p>Proudly affiliated with Cambridge Assessment International Education, ECESWA, ISASA, and OISESA.</p>', 4)
) AS s(page_slug, section_type, heading, body_html, display_order)
ON pg.slug = s.page_slug;

-- 6) Staff
WITH sid AS (SELECT id FROM schools WHERE lower(name) = lower('Sifundzani High School') LIMIT 1)
INSERT INTO school_staff (school_id, full_name, role, department, photo_url, display_order, is_active)
SELECT sid.id, x.full_name, x.role, x.department, x.photo_url, x.display_order, TRUE
FROM sid,
(VALUES
  ('Mrs. A Nzima', 'Head', NULL, 'https://sifundzani.ac.sz/assets/images/staff/principal.jpg', 1),
  ('Ms. N. Fakudze', 'Deputy Head', NULL, 'https://sifundzani.ac.sz/assets/images/staff/deputy.JPG', 2),
  ('Mr. J. Richards', 'Teacher', NULL, 'https://sifundzani.ac.sz/assets/images/staff/richards.jpg', 3),
  ('Mrs. L. Dlamini', 'Counselor', 'Counseling Psychology', 'https://sifundzani.ac.sz/assets/images/staff/counsilor.jpg', 4)
) AS x(full_name, role, department, photo_url, display_order);

-- 7) Gallery albums
WITH sid AS (SELECT id FROM schools WHERE lower(name) = lower('Sifundzani High School') LIMIT 1)
INSERT INTO school_gallery_albums (school_id, title, description, cover_image_url, category, is_published, display_order)
SELECT sid.id, x.title, x.description, x.cover_image_url, x.category, TRUE, x.display_order
FROM sid,
(VALUES
  ('Culture Day', 'Celebrating diversity and unity', 'https://sifundzani.ac.sz/assets/images/gallery/1.JPG', 'events', 1),
  ('Science Labs', 'State-of-the-art facilities', 'https://sifundzani.ac.sz/assets/images/gallery/6.jpg', 'photos', 2),
  ('Sports', 'Athletics and recreation', 'https://sifundzani.ac.sz/assets/images/gallery/9.JPG', 'events', 3),
  ('Events', 'School celebrations', 'https://sifundzani.ac.sz/assets/images/gallery/10.JPG', 'events', 4)
) AS x(title, description, cover_image_url, category, display_order);

-- 8) News
WITH sid AS (SELECT id FROM schools WHERE lower(name) = lower('Sifundzani High School') LIMIT 1)
INSERT INTO school_news (school_id, title, slug, excerpt, body_html, cover_image_url, category, author_name, published_at, is_published, is_featured, view_count)
SELECT sid.id, n.title, n.slug, n.excerpt, n.body_html, n.cover_image_url, n.category, 'Sifundzani Admin', n.published_at::timestamp, TRUE, n.is_featured, 0
FROM sid,
(VALUES
  (
    'Inter-House Sports Day 2026',
    'inter-house-sports-day-2026',
    'Ngwenya (Green House) retains the championship trophy in a thrilling day of athletics with record-breaking performances.',
    '<p>Sifu Interhouse 2026 was a day full of energy, competition and unforgettable moments. Students from all houses showcased talent, teamwork and school spirit across events. Green House (Ngwenya) emerged as overall champions.</p>',
    'https://sifundzani.ac.sz/assets/images/news/IMG_7698.JPG',
    'sports',
    '2026-03-27 09:00:00',
    TRUE
  ),
  (
    'World Water Day',
    'world-water-day-2026',
    'Small Actions, Big Impact. Save Water, Protect Our Planet.',
    '<p>World Water Day reminds us how important water is for life. At Sifundzani, students promoted habits like saving water, keeping it clean and using it responsibly.</p>',
    'https://sifundzani.ac.sz/assets/images/news/waterday.jpg',
    'environment',
    '2026-03-25 09:00:00',
    FALSE
  ),
  (
    'Youth Empowerment',
    'youth-empowerment-2026',
    'Students attended the Child Online Protection Indaba launch in Eswatini.',
    '<p>Sifundzani students attended the Child Online Protection Indaba launch held at Sibane Sami Hotel, learning about cyber safety, privacy, legal protections and responsible digital citizenship.</p>',
    'https://sifundzani.ac.sz/assets/images/news/cyberbullying.jpg',
    'youth',
    '2026-03-25 13:00:00',
    FALSE
  )
) AS n(title, slug, excerpt, body_html, cover_image_url, category, published_at, is_featured);

-- 9) Calendar events
WITH sid AS (SELECT id FROM schools WHERE lower(name) = lower('Sifundzani High School') LIMIT 1)
INSERT INTO school_events (school_id, title, description, event_date, end_date, event_type, venue, image_url, is_published, is_featured)
SELECT sid.id, e.title, e.description, e.event_date::date, NULL::date, e.event_type, e.venue, NULL, TRUE, e.is_featured
FROM sid,
(VALUES
  ('Inter-Schools Athletics Sports Day', '07:30 AM - 4:00 PM - All grades', '2026-03-27', 'sports', 'Mavuso Sports Center', TRUE),
  ('Sifundzani Book Day', '07:30 PM - 08:20 PM - All parents', '2026-04-10', 'academic', 'Tsemba Nkulunkulu Hall', FALSE),
  ('Culture Day', 'Celebrating Cultural Diversity - All students', '2026-04-16', 'cultural', 'Sifundzani Campus', FALSE),
  ('Term 1 Ends', 'Early dismissal at 12:00 PM - All students', '2026-04-16', 'academic', 'Sifundzani Campus', FALSE)
) AS e(title, description, event_date, event_type, venue, is_featured);

-- 10) Testimonials
WITH sid AS (SELECT id FROM schools WHERE lower(name) = lower('Sifundzani High School') LIMIT 1)
INSERT INTO school_testimonials (school_id, quote, author_name, author_role, author_photo_url, rating, is_featured, display_order)
SELECT sid.id, t.quote, t.author_name, t.author_role, t.author_photo_url, 5, TRUE, t.display_order
FROM sid,
(VALUES
  (
    'At Sifundzani it is not only about the intelligent quotient (IQ) of the child, I have seen my girl''s emotional intelligence (EQ) being transformed through learning and coaching into self-confident winner.',
    'Mr. Dladla',
    'Parent of student',
    'https://sifundzani.ac.sz/assets/images/system/parent1.png',
    1
  ),
  (
    'Over and above learning and instilling discipline in our children, I am intrigued by their vast and inclusive extra curricula activities, which contribute to the 360 development of our children.',
    'Miss Ndlandla',
    'Parent of student',
    'https://sifundzani.ac.sz/assets/images/system/parent2.png',
    2
  )
) AS t(quote, author_name, author_role, author_photo_url, display_order);

-- 11) Downloads and policies
WITH sid AS (SELECT id FROM schools WHERE lower(name) = lower('Sifundzani High School') LIMIT 1)
INSERT INTO school_downloads (school_id, label, description, file_url, file_type, file_size_kb, category, download_count, is_active)
SELECT sid.id, d.label, d.description, d.file_url, d.file_type, NULL, d.category, 0, TRUE
FROM sid,
(VALUES
  ('Information Booklet', 'Curriculum and school overview', 'https://sifundzani.ac.sz/download.php?file=booklet', 'pdf', 'prospectus'),
  ('School Prospectus', 'Admissions and school life', 'https://sifundzani.ac.sz/download.php?file=prospectus', 'pdf', 'prospectus'),
  ('Social Media Policy', 'School policy', 'https://sifundzani.ac.sz/download.php?file=social', 'pdf', 'policies'),
  ('Academic Honesty Policy', 'School policy', 'https://sifundzani.ac.sz/download.php?file=honesty', 'pdf', 'policies'),
  ('Inclusion and Diversity Policy', 'School policy', 'https://sifundzani.ac.sz/download.php?file=inclusion', 'pdf', 'policies'),
  ('Anti-Bullying', 'School policy', 'https://sifundzani.ac.sz/download.php?file=anti-bullying', 'pdf', 'policies')
) AS d(label, description, file_url, file_type, category);

-- 12) Contact info
WITH sid AS (SELECT id FROM schools WHERE lower(name) = lower('Sifundzani High School') LIMIT 1)
INSERT INTO school_contact_info (
  school_id, address_line1, address_line2, city, country, postal_code,
  phone_primary, phone_secondary, email_primary, email_secondary, maps_embed_url,
  coordinates_lat, coordinates_lng
)
SELECT
  sid.id,
  'Pine Valley Road',
  'P.O. BOX 259 Eveni',
  'Mbabane',
  'Eswatini',
  'H100',
  '(+268) 24041157 / 24043859 / 24043857',
  NULL,
  'info@sifundzani.ac.sz',
  NULL,
  'https://www.google.com/maps?q=Mbabane,+Eswatini&output=embed',
  -26.3167,
  31.1333
FROM sid;

-- 13) Social links
WITH sid AS (SELECT id FROM schools WHERE lower(name) = lower('Sifundzani High School') LIMIT 1)
INSERT INTO school_social_links (school_id, platform, url, display_order)
SELECT sid.id, s.platform, s.url, s.display_order
FROM sid,
(VALUES
  ('facebook', 'https://www.facebook.com/SifundzaniHighSchool', 1),
  ('instagram', 'https://www.instagram.com/', 2),
  ('youtube', 'https://www.youtube.com/', 3),
  ('whatsapp', 'https://wa.me/+26879643515?text=Hello%20Sifundzani%2C%20I%27m%20interested%20in%20enrolling', 4)
) AS s(platform, url, display_order);

-- 14) Page media
WITH sid AS (
  SELECT id FROM schools WHERE lower(name) = lower('Sifundzani High School') LIMIT 1
), pg AS (
  SELECT id, slug FROM school_pages WHERE school_id = (SELECT id FROM sid)
)
INSERT INTO school_media (school_id, page_id, media_type, file_url, alt_text, caption, file_name, mime_type, display_order)
SELECT (SELECT id FROM sid), pg.id, m.media_type, m.file_url, m.alt_text, m.caption, m.file_name, m.mime_type, m.display_order
FROM pg
JOIN (
  VALUES
  ('home', 'image', 'https://sifundzani.ac.sz/assets/images/system/view.png', 'School facilities', 'Modern Labs', 'view.png', 'image/png', 1),
  ('home', 'image', 'https://sifundzani.ac.sz/assets/images/system/classroom.png', 'Sifundzani students', 'Students', 'classroom.png', 'image/png', 2),
  ('admissions', 'image', 'https://sifundzani.ac.sz/assets/images/system/lab.png', 'Science Lab', 'Modern Labs', 'lab.png', 'image/png', 1),
  ('admissions', 'image', 'https://sifundzani.ac.sz/assets/images/system/sports.png', 'Sports', 'Sports Excellence', 'sports.png', 'image/png', 2),
  ('admissions', 'image', 'https://sifundzani.ac.sz/assets/images/system/library.jpg', 'Library', 'Resource Centre', 'library.jpg', 'image/jpeg', 3),
  ('admissions', 'image', 'https://sifundzani.ac.sz/assets/images/system/graduation.png', 'Graduation', 'Graduate Success', 'graduation.png', 'image/png', 4),
  ('about', 'image', 'https://sifundzani.ac.sz/assets/images/system/primary.jpg', 'School History', 'School History', 'primary.jpg', 'image/jpeg', 1)
) AS m(page_slug, media_type, file_url, alt_text, caption, file_name, mime_type, display_order)
ON pg.slug = m.page_slug;

-- 15) Optional accreditation media entries (stored under contact page)
WITH sid AS (
  SELECT id FROM schools WHERE lower(name) = lower('Sifundzani High School') LIMIT 1
), pg AS (
  SELECT id FROM school_pages WHERE school_id = (SELECT id FROM sid) AND slug = 'contact' LIMIT 1
)
INSERT INTO school_media (school_id, page_id, media_type, file_url, alt_text, caption, file_name, mime_type, display_order)
SELECT (SELECT id FROM sid), (SELECT id FROM pg), 'image', x.file_url, x.alt_text, x.caption, x.file_name, 'image/png', x.display_order
FROM (
  VALUES
  ('https://sifundzani.ac.sz/assets/icons/cambridge.png', 'Cambridge Assessment', 'Cambridge', 'cambridge.png', 20),
  ('https://sifundzani.ac.sz/assets/icons/eceswa.png', 'Exams Council of Eswatini', 'ECESWA', 'eceswa.png', 21),
  ('https://sifundzani.ac.sz/assets/icons/isasa.png', 'ISASA', 'ISASA', 'isasa.png', 22),
  ('https://sifundzani.ac.sz/assets/icons/oesesa.png', 'OISESA', 'OISESA', 'oesesa.png', 23)
) AS x(file_url, alt_text, caption, file_name, display_order);

-- =============================================================================
-- END
-- =============================================================================
