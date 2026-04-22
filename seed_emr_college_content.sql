-- =============================================================================
-- Seed content for Emergency Medical Rescue College into dynamic school-site tables
-- Source note: On 2026-04-18 the live host did not resolve from this environment.
-- This seed uses only publicly verifiable cached homepage content and public
-- WordPress page payloads that were accessible at that time.
-- =============================================================================

-- Ensure per-school CSS/template columns exist
ALTER TABLE schools ADD COLUMN IF NOT EXISTS custom_css TEXT;
ALTER TABLE schools ADD COLUMN IF NOT EXISTS layout_template VARCHAR(80);

-- Ensure EMR College school exists
INSERT INTO schools (name, school_type, location, logo, contact_number, contact_email)
SELECT
  'Emergency Medical Rescue College',
  'tertiary',
  'Eswatini',
  NULL,
  '+268 7872 1887',
  'info@emrcollege.com'
WHERE NOT EXISTS (
  SELECT 1
  FROM schools
  WHERE lower(name) IN (
    lower('Emergency Medical Rescue College'),
    lower('EMR College')
  )
     OR lower(name) LIKE '%emergency medical rescue%'
     OR lower(name) LIKE '%emr college%'
);

-- 1) Resolve school id and update brand/profile fields
WITH sid AS (
  SELECT id
  FROM schools
  WHERE lower(name) IN (
    lower('Emergency Medical Rescue College'),
    lower('EMR College')
  )
     OR lower(name) LIKE '%emergency medical rescue%'
     OR lower(name) LIKE '%emr college%'
  ORDER BY id
  LIMIT 1
)
UPDATE schools s
SET
  tagline = 'We Train The Brave',
  motto = 'We Train The Brave',
  primary_color = '#0B4EA2',
  accent_color = '#F58220',
  contact_number = '+268 7872 1887',
  contact_email = 'info@emrcollege.com',
  hero_image_url = 'https://emrcollege.ac.sz/wp-content/uploads/2024/04/IMG_8497-scaled.jpg',
  layout_template = 'premium_university_v2',
  is_active = TRUE,
  custom_css = '.hero-panel-note{font-size:.88rem}.menu a.active{background:#F58220;border-color:#F58220;color:#0b1a2f}.menu a.hub-link,.menu a.auth-link,.menu a.apply-link{background:#ffffff;border-color:#ffffff;color:#0B4EA2}.section{background:linear-gradient(145deg,rgba(255,255,255,.18),rgba(255,255,255,.08))}'
FROM sid
WHERE s.id = sid.id;

-- 2) Clear old dynamic content for EMR College (idempotent reseed)
WITH sid AS (
  SELECT id
  FROM schools
  WHERE lower(name) IN (
    lower('Emergency Medical Rescue College'),
    lower('EMR College')
  )
     OR lower(name) LIKE '%emergency medical rescue%'
     OR lower(name) LIKE '%emr college%'
  ORDER BY id
  LIMIT 1
)
DELETE FROM school_menu WHERE school_id IN (SELECT id FROM sid);

WITH sid AS (
  SELECT id
  FROM schools
  WHERE lower(name) IN (
    lower('Emergency Medical Rescue College'),
    lower('EMR College')
  )
     OR lower(name) LIKE '%emergency medical rescue%'
     OR lower(name) LIKE '%emr college%'
  ORDER BY id
  LIMIT 1
)
DELETE FROM school_sections WHERE school_id IN (SELECT id FROM sid);

WITH sid AS (
  SELECT id
  FROM schools
  WHERE lower(name) IN (
    lower('Emergency Medical Rescue College'),
    lower('EMR College')
  )
     OR lower(name) LIKE '%emergency medical rescue%'
     OR lower(name) LIKE '%emr college%'
  ORDER BY id
  LIMIT 1
)
DELETE FROM school_pages WHERE school_id IN (SELECT id FROM sid);

WITH sid AS (
  SELECT id
  FROM schools
  WHERE lower(name) IN (
    lower('Emergency Medical Rescue College'),
    lower('EMR College')
  )
     OR lower(name) LIKE '%emergency medical rescue%'
     OR lower(name) LIKE '%emr college%'
  ORDER BY id
  LIMIT 1
)
DELETE FROM school_staff WHERE school_id IN (SELECT id FROM sid);

WITH sid AS (
  SELECT id
  FROM schools
  WHERE lower(name) IN (
    lower('Emergency Medical Rescue College'),
    lower('EMR College')
  )
     OR lower(name) LIKE '%emergency medical rescue%'
     OR lower(name) LIKE '%emr college%'
  ORDER BY id
  LIMIT 1
)
DELETE FROM school_gallery_albums WHERE school_id IN (SELECT id FROM sid);

WITH sid AS (
  SELECT id
  FROM schools
  WHERE lower(name) IN (
    lower('Emergency Medical Rescue College'),
    lower('EMR College')
  )
     OR lower(name) LIKE '%emergency medical rescue%'
     OR lower(name) LIKE '%emr college%'
  ORDER BY id
  LIMIT 1
)
DELETE FROM school_news WHERE school_id IN (SELECT id FROM sid);

WITH sid AS (
  SELECT id
  FROM schools
  WHERE lower(name) IN (
    lower('Emergency Medical Rescue College'),
    lower('EMR College')
  )
     OR lower(name) LIKE '%emergency medical rescue%'
     OR lower(name) LIKE '%emr college%'
  ORDER BY id
  LIMIT 1
)
DELETE FROM school_events WHERE school_id IN (SELECT id FROM sid);

WITH sid AS (
  SELECT id
  FROM schools
  WHERE lower(name) IN (
    lower('Emergency Medical Rescue College'),
    lower('EMR College')
  )
     OR lower(name) LIKE '%emergency medical rescue%'
     OR lower(name) LIKE '%emr college%'
  ORDER BY id
  LIMIT 1
)
DELETE FROM school_testimonials WHERE school_id IN (SELECT id FROM sid);

WITH sid AS (
  SELECT id
  FROM schools
  WHERE lower(name) IN (
    lower('Emergency Medical Rescue College'),
    lower('EMR College')
  )
     OR lower(name) LIKE '%emergency medical rescue%'
     OR lower(name) LIKE '%emr college%'
  ORDER BY id
  LIMIT 1
)
DELETE FROM school_downloads WHERE school_id IN (SELECT id FROM sid);

WITH sid AS (
  SELECT id
  FROM schools
  WHERE lower(name) IN (
    lower('Emergency Medical Rescue College'),
    lower('EMR College')
  )
     OR lower(name) LIKE '%emergency medical rescue%'
     OR lower(name) LIKE '%emr college%'
  ORDER BY id
  LIMIT 1
)
DELETE FROM school_contact_info WHERE school_id IN (SELECT id FROM sid);

WITH sid AS (
  SELECT id
  FROM schools
  WHERE lower(name) IN (
    lower('Emergency Medical Rescue College'),
    lower('EMR College')
  )
     OR lower(name) LIKE '%emergency medical rescue%'
     OR lower(name) LIKE '%emr college%'
  ORDER BY id
  LIMIT 1
)
DELETE FROM school_social_links WHERE school_id IN (SELECT id FROM sid);

WITH sid AS (
  SELECT id
  FROM schools
  WHERE lower(name) IN (
    lower('Emergency Medical Rescue College'),
    lower('EMR College')
  )
     OR lower(name) LIKE '%emergency medical rescue%'
     OR lower(name) LIKE '%emr college%'
  ORDER BY id
  LIMIT 1
)
DELETE FROM school_media WHERE school_id IN (SELECT id FROM sid);

-- 3) Navigation tabs verified/minimized for the current accessible site snapshot
WITH sid AS (
  SELECT id
  FROM schools
  WHERE lower(name) IN (
    lower('Emergency Medical Rescue College'),
    lower('EMR College')
  )
     OR lower(name) LIKE '%emergency medical rescue%'
     OR lower(name) LIKE '%emr college%'
  ORDER BY id
  LIMIT 1
)
INSERT INTO school_menu (school_id, label, slug, display_order, is_external, external_url, is_active)
SELECT sid.id, m.label, m.slug, m.display_order, FALSE, NULL, TRUE
FROM sid,
(VALUES
  ('Home', 'home', 1),
  ('About us', 'about', 2),
  ('Courses', 'courses', 3),
  ('Vacancies', 'vacancies', 4),
  ('Contact', 'contact', 5)
) AS m(label, slug, display_order);

-- 4) Pages
WITH sid AS (
  SELECT id
  FROM schools
  WHERE lower(name) IN (
    lower('Emergency Medical Rescue College'),
    lower('EMR College')
  )
     OR lower(name) LIKE '%emergency medical rescue%'
     OR lower(name) LIKE '%emr college%'
  ORDER BY id
  LIMIT 1
)
INSERT INTO school_pages (school_id, slug, title, meta_description, hero_image_url, is_published)
SELECT sid.id, p.slug, p.title, p.meta_description, p.hero_image_url, TRUE
FROM sid,
(VALUES
  ('home', 'We Train The Brave', 'Emergency Medical Rescue College public website content captured from the accessible homepage snapshot.', 'https://emrcollege.ac.sz/wp-content/uploads/2024/04/IMG_8497-scaled.jpg'),
  ('about', 'About EMR College', 'Emergency Medical Rescue College overview and institutional profile.', 'https://emrcollege.ac.sz/wp-content/uploads/2024/04/IMG_8497-scaled.jpg'),
  ('courses', 'Courses', 'Explore programme details and entrance requirements.', 'https://emrcollege.ac.sz/wp-content/uploads/2024/04/skills-lab-lectur-7-scaled.jpg'),
  ('vacancies', 'Current Vacancies', 'Public recruitment notices extracted from the EMR College WordPress pages feed.', 'https://emrcollege.ac.sz/wp-content/uploads/2024/04/skills-lab-lectur-9-scaled.jpg'),
  ('admissions', 'Application Form', 'The EMR homepage publicly exposes an Application Form section and programme list.', 'https://emrcollege.ac.sz/wp-content/uploads/2024/04/6-12-scaled.jpg'),
  ('contact', 'Contact', 'Emergency Medical Rescue College contact details.', 'https://emrcollege.ac.sz/wp-content/uploads/2024/04/skills-lab-lectur-7-scaled.jpg'),
  ('course-bhs-emcr', 'Bachelor of Health Science in Emergency Medical Care and Rescue', 'Programme details for Bachelor of Health Science in Emergency Medical Care and Rescue.', 'https://emrcollege.ac.sz/wp-content/uploads/2024/04/skills-lab-lectur-7-scaled.jpg'),
  ('course-diploma-emcr', 'Diploma in Emergency Medical Care and Rescue', 'Programme details for Diploma in Emergency Medical Care and Rescue.', 'https://emrcollege.ac.sz/wp-content/uploads/2024/04/6-12-scaled.jpg'),
  ('course-diploma-osh', 'Diploma in Occupational Safety and Health', 'Programme details for Diploma in Occupational Safety and Health.', 'https://emrcollege.ac.sz/wp-content/uploads/2024/04/skills-lab-lectur-7-scaled.jpg')
) AS p(slug, title, meta_description, hero_image_url);

-- 5) Sections
WITH sid AS (
  SELECT id
  FROM schools
  WHERE lower(name) IN (
    lower('Emergency Medical Rescue College'),
    lower('EMR College')
  )
     OR lower(name) LIKE '%emergency medical rescue%'
     OR lower(name) LIKE '%emr college%'
  ORDER BY id
  LIMIT 1
), pg AS (
  SELECT id, slug
  FROM school_pages
  WHERE school_id = (SELECT id FROM sid)
)
INSERT INTO school_sections (school_id, page_id, section_type, heading, body_html, display_order, is_visible)
SELECT (SELECT id FROM sid), pg.id, s.section_type, s.heading, s.body_html, s.display_order, TRUE
FROM pg
JOIN (
  VALUES
  ('home', 'text_block', 'Application Form', '<p>The publicly accessible homepage snapshot begins with an <strong>Application Form</strong> callout. The live application destination was not exposed in the accessible cache, so this seed stores the verified section heading and study offering without inventing a hidden link.</p>', 1),
  ('home', 'text_block', 'Main Programmes', '<ul><li><strong>Bachelor of Health Science in Emergency Medical Care and Rescue</strong> - Designed to produce an advanced-level health worker whose capabilities enable delivery of emergency care services within the Kingdom of Eswatini.</li><li><strong>Diploma in Emergency Medical Care and Rescue</strong> - Three-year full-time programme over six semesters combining classroom lectures with work-integrated learning in public and private sector settings.</li><li><strong>Diploma in Occupational Safety and Health</strong> - Two-year programme assessed through continuous assessment and formal semester examinations.</li><li><strong>Certificate in Emergency Medical Care and Rescue</strong> - One-year full-time programme over two semesters with classroom, practical, and work-integrated learning.</li></ul>', 2),
  ('home', 'text_block', 'Programme Read More Links', '<p><a href="/school/{{ school.id if school and school.id else 0 }}/course-bhs-emcr">Bachelor of Health Science in Emergency Medical Care and Rescue - Read more</a></p><p><a href="/school/{{ school.id if school and school.id else 0 }}/course-diploma-emcr">Diploma in Emergency Medical Care and Rescue - Read more</a></p><p><a href="/school/{{ school.id if school and school.id else 0 }}/course-diploma-osh">Diploma in Occupational Safety and Health - Read more</a></p><p>Certificate in Emergency Medical Care and Rescue currently has no additional read-more content.</p>', 3),
  ('home', 'text_block', 'Introducing Our Exciting New Programs', '<ul><li><strong>Diploma in Rescue Technology</strong> - Four-semester training for rescue technicians with rescue specialization and basic medical assistance skills.</li><li><strong>Diploma in Disaster Management</strong> - Four-semester programme focused on disaster management practice, advice, and response capacity.</li><li><strong>Diploma in Beauty Therapy and Aesthetics</strong> - A diploma for learners pursuing careers in the beauty and wellness industry.</li><li><strong>Diploma in Public Health</strong> - Six-semester programme preparing qualified professionals in public health through teaching, research, and community outreach.</li></ul>', 3),
  ('home', 'text_block', 'Recruitment Snapshot', '<p>Accessible public pages on the site currently include vacancy notices for <strong>IT Intern</strong>, <strong>DRRM Lecturer</strong>, <strong>Lecturer 1 &amp; 2</strong>, and a <strong>Registrar Position</strong> posting.</p>', 4),

  ('about', 'text_block', 'About EMR College', '<p>Emergency Medical Rescue College is focused on training competent emergency medical and rescue professionals through practical, work-integrated learning.</p>', 1),

  ('courses', 'text_block', 'Main Programmes', '<ul><li><a href="/school/{{ school.id if school and school.id else 0 }}/course-bhs-emcr">Bachelor of Health Science in Emergency Medical Care and Rescue</a></li><li><a href="/school/{{ school.id if school and school.id else 0 }}/course-diploma-emcr">Diploma in Emergency Medical Care and Rescue</a></li><li><a href="/school/{{ school.id if school and school.id else 0 }}/course-diploma-osh">Diploma in Occupational Safety and Health</a></li><li>Certificate in Emergency Medical Care and Rescue (no read-more page provided yet).</li></ul>', 1),

  ('course-bhs-emcr', 'text_block', 'Background', '<p>Bachelor of Health Science in Emergency Medical Care and Rescue is a dynamic and challenging program designed to equip students with the knowledge and skills necessary to respond to medical emergencies and provide life-saving care. This comprehensive degree program integrates a strong foundation in health science with specialized training in emergency medical care and rescue techniques.</p>', 1),
  ('course-bhs-emcr', 'text_block', 'Entrance Requirements', '<p>A minimum (Average) of 35 points for Form 5 SGCSE/IGCSE/GCE/O''Level qualify prospective students. Mathematics, Biology, Physics and Chemistry will be an added advantage.</p><p>Diploma in emergency medical care &amp; rescue or any equivalent qualification for employed prospective students. The applicant should also:</p><p>Pass the fitness assessment, present a current medical examination and pass an interview with the college rep.</p>', 2),
  ('course-bhs-emcr', 'text_block', 'Course Structure', '<p>Bachelor of Health Science in Emergency Medical Care &amp; Rescue is designed to produce an advanced-level health worker whose capabilities enable to provide emergency care services within the Kingdom of Eswatini. The Bachelor of Health Science in Emergency Medical Care &amp; Rescue (BHS in EMCR) will play a vital role in introducing graduates to research methods and how to conduct scientific research within the Eswatini health care sector, it will enable students to effectively challenge the status quo through adopting a problem-solving approach that is based on the existing evidence at the time.</p>', 3),
  ('course-bhs-emcr', 'text_block', 'Course Fees', '<p>Year 1: E 34 565.00</p><p>Year 2: E 34 660.00</p><p>Year 3: E 36 755.00</p><p>Year 4: E 36 600.00</p>', 4),
  ('course-bhs-emcr', 'download_list', 'Download Prospectors', '<p>Prospectus download button included as requested; file link can be replaced later.</p>', 5),

  ('course-diploma-emcr', 'text_block', 'Background', '<p>The programme is a Three (3) year full time course running over six (6) semesters. The program comprises of classroom lectures and practical series of work-integrated learning taking place in both public and private sector in the Kingdom of Eswatini.</p>', 1),
  ('course-diploma-emcr', 'text_block', 'Entrance Requirements', '<p>A minimum (Average) of 30 points for Form 5 SGCSE/IGCSE/GCE/O''Level qualify prospective students. Biology, Physics and Chemistry will be added advantage.</p><p>Employed prospective students without form 5, will have to apply for Recognized Prior Learning (RPL). The applicant should also: Pass the fitness assessment and pass an interview with the college representative.</p>', 2),
  ('course-diploma-emcr', 'text_block', 'Course Structure', '<p>The program is a three (3) year full time course running over six (6) semesters. The program comprises of classroom lectures and practical series of work-integrated learning taking place in both public and private sector in the Kingdom of Eswatini.</p>', 3),
  ('course-diploma-emcr', 'text_block', 'Course Fees', '<p>Semester 1: E 17 385.00</p><p>Semester 2: E 15 540.00</p><p>Semester 3: E 18 685.00</p><p>Semester 4: E 15 670.00</p><p>Semester 5: E 15 670.00</p><p>Semester 6: E 14 515.00</p>', 4),
  ('course-diploma-emcr', 'download_list', 'Download Prospectors', '<p>Prospectus download button included as requested; file link can be replaced later.</p>', 5),

  ('course-diploma-osh', 'text_block', 'Background', '<p>Diploma in Occupational Safety and Health (DOSH) is a comprehensive program designed to equip individuals with the knowledge and skills necessary to ensure a safe and healthy work environment. This diploma program focuses on various aspects of occupational safety and health, including risk assessment, hazard identification, emergency preparedness, and regulatory compliance.</p>', 1),
  ('course-diploma-osh', 'text_block', 'Entrance Requirements', '<p>A minimum (Average) of 30 points for Form 5 qualified prospective students. English and Mathematics will be added advantage. Employed prospective students without Form 5 will have to apply for Recognized Prior Learning (RPL).</p>', 2),
  ('course-diploma-osh', 'text_block', 'Course Structure', '<p>Diploma in Occupational Safety and Health shall be of two years'' duration. Assessments shall occur through continuous assessment and formal examination per semester.</p>', 3),
  ('course-diploma-osh', 'text_block', 'Course Fees', '<p>Semester 1: E 9 435.00</p><p>Semester 2: E 9 250.00</p><p>Semester 3: E 9 150.00</p><p>Semester 4: E 8745.00</p>', 4),
  ('course-diploma-osh', 'download_list', 'Download Prospectors', '<p>Prospectus download button included as requested; file link can be replaced later.</p>', 5),

  ('vacancies', 'text_block', 'Public Vacancy Notices', '<p>These notices were extracted from the public EMR College WordPress pages feed that remained reachable while the main hostname itself was not resolving in this environment.</p>', 1),
  ('vacancies', 'news_feed', 'Open Positions', '<p>Each card below corresponds to a publicly published vacancy page discovered for EMR College.</p>', 2),

  ('admissions', 'text_block', 'Study Opportunities', '<p>The accessible homepage promotes an <strong>Application Form</strong> and lists certificate, diploma, and bachelor-level study options in emergency care, occupational safety, rescue technology, disaster management, beauty therapy, and public health.</p>', 1),
  ('admissions', 'text_block', 'Programmes Verified In Public Snapshot', '<p>Bachelor of Health Science in Emergency Medical Care and Rescue, Diploma in Emergency Medical Care and Rescue, Diploma in Occupational Safety and Health, Certificate in Emergency Medical Care and Rescue, Diploma in Rescue Technology, Diploma in Disaster Management, Diploma in Beauty Therapy and Aesthetics, and Diploma in Public Health.</p>', 2),

  ('contact', 'contact_map', 'Contact', '<p>The only publicly verifiable direct contact recovered from the accessible site snapshot was <strong>hroemrc@gmail.com</strong>, which appeared on multiple vacancy pages as the submission email for applications.</p>', 1),
  ('contact', 'text_block', 'Website Availability Note', '<p>The EMR host returned DNS resolution failure from this environment on 2026-04-18, so this seed intentionally limits contact content to facts that were still publicly verifiable through accessible cached pages.</p>', 2)
) AS s(page_slug, section_type, heading, body_html, display_order)
ON pg.slug = s.page_slug;

-- 5b) Fix internal read-more links now that school_id is known
WITH sid AS (
  SELECT id
  FROM schools
  WHERE lower(name) IN (lower('Emergency Medical Rescue College'), lower('EMR College'))
     OR lower(name) LIKE '%emergency medical rescue%'
     OR lower(name) LIKE '%emr college%'
  ORDER BY id
  LIMIT 1
)
UPDATE school_sections
SET body_html = REPLACE(body_html, '/school/{{ school.id if school and school.id else 0 }}/', '/school/' || (SELECT id FROM sid) || '/')
WHERE school_id = (SELECT id FROM sid)
  AND body_html LIKE '%/school/{{ school.id if school and school.id else 0 }}/%';

-- 6) Vacancy pages stored as news items for the tertiary template
WITH sid AS (
  SELECT id
  FROM schools
  WHERE lower(name) IN (
    lower('Emergency Medical Rescue College'),
    lower('EMR College')
  )
     OR lower(name) LIKE '%emergency medical rescue%'
     OR lower(name) LIKE '%emr college%'
  ORDER BY id
  LIMIT 1
)
INSERT INTO school_news (school_id, title, slug, excerpt, body_html, cover_image_url, category, author_name, published_at, is_published, is_featured, view_count)
SELECT sid.id, n.title, n.slug, n.excerpt, n.body_html, n.cover_image_url, 'vacancy', 'EMR College Website', n.published_at::timestamp, TRUE, n.is_featured, 0
FROM sid,
(VALUES
  (
    'IT Intern',
    'it-intern',
    'The IT & Academic Support Intern supports daily IT operations and academic computer-lab activities while gaining practical experience in systems maintenance and classroom assistance.',
    '<p><strong>Job Title: IT INTERN</strong></p><h4>Context</h4><p>The IT &amp; Academic Support Intern will assist in the daily operations of the IT Department and support academic activities within the computer lab. The role is designed to provide practical experience in IT support, systems maintenance, and classroom assistance while contributing to the efficiency of the department.</p><h4>Key Responsibilities</h4><h4>1. Academic Support</h4><ul><li>Assist during practical computer lessons and support students with tasks.</li><li>Help prepare learning materials and set up for classes.</li><li>Assist with marking assignments, tests, and basic record-keeping.</li><li>Provide basic guidance to students on computer usage and applications.</li></ul><h4>2. Computer Lab Management</h4><ul><li>Set up and prepare the computer lab before classes.</li><li>Ensure all computers, projectors, and equipment are functional.</li><li>Report faults or issues with equipment.</li><li>Assist during events, meetings, and presentations requiring IT setup.</li></ul><h4>Minimum Requirements</h4><ul><li>Diploma or Associate Degree in Information Technology, Computer Science, or related field.</li><li>Basic knowledge of computer hardware, software, and networking.</li><li>Familiarity with Microsoft Office and common applications.</li><li>Willingness to learn and take initiative.</li></ul><h4>How to Apply</h4><ul><li>Send your CV, Certified academic documents and a cover letter to <strong>hroemrc@gmail.com</strong> with the subject lines; IT &amp; Academic Support Intern.</li></ul><p><strong>Closing date; 22/04/2026.</strong></p><p><a href="https://emrcollege.ac.sz/index.php/elementor-page-9102/" target="_blank" rel="noopener">Original public page</a></p>',
    'https://emrcollege.ac.sz/wp-content/uploads/2024/04/6-12-scaled.jpg',
    '2026-04-15 14:34:51',
    TRUE
  ),
  (
    'DRRM Lecturer',
    'drrm-lecturer',
    'EMR College published a DRRM Lecturer role focused on teaching disaster management, research, curriculum development, and consultancy in disaster risk reduction.',
    '<p><strong>Job Title: DRRM LECTURER</strong></p><h4>Context</h4><p>We are a dynamic and growing Institution, committed to Academic excellence in the field of higher education. We value integrity, teamwork, and innovation, and we''re looking for a detail-oriented Lecturer to join our Emergency Medical Rescue College team.</p><h4>Key Responsibilities</h4><ul><li>Develop and teach courses on various aspects of disaster management.</li><li>Deliver lectures, facilitate discussions, and provide individual student support.</li><li>Conduct independent research on disaster management topics.</li><li>Collaborate with other researchers and practitioners to advance knowledge in the field.</li><li>Participate in curriculum development initiatives for the disaster management program.</li><li>Provide consultancy services on disaster risk reduction and mitigation strategies.</li></ul><h4>Requirements &amp; Qualifications</h4><ul><li>PhD or Master''s degree in Disaster Management, Emergency Management, Environmental Science, Geography or a related field.</li><li>Proven teaching experience in disaster management at the undergraduate and/or Postgraduate level for 3 to 5 years.</li><li>Strong research background with publications in peer-reviewed journals.</li><li>Familiarity with disaster management frameworks, methodologies, and best practices.</li><li>Excellent communication and interpersonal skills to effectively interact with students, Colleagues, and external stakeholders.</li></ul><h4>How to Apply</h4><ul><li>How to Apply</li></ul><p>Send your CV, Certified academic documents and a cover letter to <strong>hroemrc@gmail.com</strong> with the subject line DRRM Lecturer Job Application.</p><p><strong>Closing date 30/04/2026.</strong></p><p><a href="https://emrcollege.ac.sz/index.php/drrm-lecturer/" target="_blank" rel="noopener">Original public page</a></p>',
    'https://emrcollege.ac.sz/wp-content/uploads/2024/04/skills-lab-lectur-9-scaled.jpg',
    '2026-04-15 14:26:39',
    TRUE
  ),
  (
    'Lecturer 1 & 2',
    'lecturer-1-and-2',
    'This public vacancy covers two lecturer tracks: Nursing Background and Medicine Background, both aimed at training future emergency medical and healthcare professionals.',
    '<p><strong>Job Title: LECTURER 1 &amp; 2</strong></p><h4>Context</h4><h4>1. Lecturer - Nursing Background</h4><p>The college seeks a qualified nurse educator to support the training of future emergency medical and healthcare professionals.</p><h4>Key Responsibilities</h4><ul><li>Deliver lectures and practical instruction in nursing and clinical sciences relevant to emergency medical care.</li><li>Facilitate simulation training, clinical skills development, and case-based learning.</li><li>Support students during clinical placements and professional practice training.</li><li>Contribute to curriculum development and continuous improvement of training programmes.</li><li>Participate in academic assessment, moderation, and student mentorship.</li><li>Engage in professional development and applied research activities.</li><li>Contribute to community outreach, health education, and public health initiatives where applicable.</li></ul><h4>Requirements and Qualifications</h4><ul><li>Bachelor''s degree in Nursing as a foundational qualification.</li><li>Master''s degree in Nursing or Public Health.</li><li>A PhD in a related field will be considered an added advantage.</li><li>Minimum 3 years teaching or clinical experience.</li><li>Registration with the Eswatini Nursing Council or eligibility for registration.</li><li>Strong clinical, teaching, and communication skills.</li></ul><h4>2. Lecturer - Medicine Background</h4><p>The college invites applications from medical professionals who are passionate about training future healthcare and emergency response professionals.</p><h4>Key Responsibilities</h4><ul><li>Deliver lectures in medical sciences relevant to emergency medicine and clinical care.</li><li>Facilitate case-based learning, clinical reasoning, and emergency care simulations.</li><li>Support students in developing clinical decision-making and patient management skills.</li><li>Participate in curriculum development and academic programme review.</li><li>Provide mentorship and academic guidance to students.</li><li>Contribute to interdisciplinary teaching within emergency medical and health sciences programmes.</li><li>Participate in research and academic development initiatives within the college.</li></ul><h4>Requirements and Qualifications</h4><ul><li>Degree in Medicine (MBBS or MBChB).</li><li>Registration with the Eswatini Medical and Dental Council (EMDC).</li><li>Minimum 2 years clinical or teaching experience.</li><li>Interest in medical education and emergency healthcare training.</li><li>Strong communication, teaching, and leadership skills.</li></ul><h4>How to Apply</h4><p>Interested candidates should submit the following documents:</p><ul><li>Curriculum Vitae (CV)</li><li>Certified academic certificates and transcripts</li><li>Certified professional registration documents (where applicable)</li><li>A cover letter indicating the position applied for</li></ul><p>Applications should be sent to: <strong>hroemrc@gmail.com</strong></p><p>Please indicate the subject line as one of the following:</p><ul><li>Lecturer - Nursing Background</li><li>Lecturer - Medicine Background</li></ul><p><strong>Application Closing Date: 30 April 2026</strong></p><p><a href="https://emrcollege.ac.sz/index.php/elementor-page-9069/" target="_blank" rel="noopener">Original public page</a></p>',
    'https://emrcollege.ac.sz/wp-content/uploads/2024/04/skills-lab-lectur-7-scaled.jpg',
    '2026-04-15 14:00:52',
    TRUE
  ),
  (
    'Registrar Position',
    'registrar-position',
    'A public page titled Registrar Position appears on the EMR College site and invites suitably qualified candidates to fill a newly established registrar post.',
    '<p><strong>Public page note:</strong> The visible page content refers to the Eswatini University of Applied Sciences (ESUAS) and states that the institution plans to open in August 2026 with accredited Certificate, Diploma, and Degree programmes. It invites suitably qualified candidates to fill a newly established <strong>Registrar</strong> position as soon as possible.</p><p>The accessible payload did not expose further application details in this environment, but the page itself was publicly published and is included here to avoid omitting a live website item.</p><p><a href="https://emrcollege.ac.sz/index.php/elementor-page-9001/" target="_blank" rel="noopener">Original public page</a></p>',
    NULL,
    '2026-02-12 12:43:14',
    FALSE
  )
) AS n(title, slug, excerpt, body_html, cover_image_url, published_at, is_featured);

-- 7) Contact info limited to verified public details
WITH sid AS (
  SELECT id
  FROM schools
  WHERE lower(name) IN (
    lower('Emergency Medical Rescue College'),
    lower('EMR College')
  )
     OR lower(name) LIKE '%emergency medical rescue%'
     OR lower(name) LIKE '%emr college%'
  ORDER BY id
  LIMIT 1
)
INSERT INTO school_contact_info (
  school_id,
  address_line1,
  address_line2,
  city,
  country,
  postal_code,
  phone_primary,
  phone_secondary,
  email_primary,
  email_secondary,
  maps_embed_url,
  coordinates_lat,
  coordinates_lng
)
SELECT
  sid.id,
  'Emergency Medical Rescue College',
  NULL,
  NULL,
  'Eswatini',
  NULL,
  '+268 7872 1887',
  NULL,
  'info@emrcollege.com',
  'hroemrc@gmail.com',
  NULL,
  NULL,
  NULL
FROM sid;

-- 7b) Social links visible on EMR header (icons)
WITH sid AS (
  SELECT id
  FROM schools
  WHERE lower(name) IN (
    lower('Emergency Medical Rescue College'),
    lower('EMR College')
  )
     OR lower(name) LIKE '%emergency medical rescue%'
     OR lower(name) LIKE '%emr college%'
  ORDER BY id
  LIMIT 1
)
INSERT INTO school_social_links (school_id, platform, url, display_order)
SELECT sid.id, s.platform, s.url, s.display_order
FROM sid,
(VALUES
  ('facebook', 'https://www.facebook.com/', 1),
  ('instagram', 'https://www.instagram.com/', 2),
  ('linkedin', 'https://www.linkedin.com/', 3)
) AS s(platform, url, display_order);

-- 7c) Prospectus placeholders (replace file links when ready)
WITH sid AS (
  SELECT id
  FROM schools
  WHERE lower(name) IN (
    lower('Emergency Medical Rescue College'),
    lower('EMR College')
  )
     OR lower(name) LIKE '%emergency medical rescue%'
     OR lower(name) LIKE '%emr college%'
  ORDER BY id
  LIMIT 1
)
INSERT INTO school_downloads (school_id, label, description, file_url, file_type, file_size_kb, category, download_count, is_active)
SELECT sid.id, d.label, d.description, d.file_url, d.file_type, NULL, d.category, 0, TRUE
FROM sid,
(VALUES
  ('Bachelor of Health Science EMCR - Prospectors', 'Temporary placeholder link. Replace with official prospectus file.', 'https://emrcollege.ac.sz/', 'pdf', 'prospectus'),
  ('Diploma in Emergency Medical Care and Rescue - Prospectors', 'Temporary placeholder link. Replace with official prospectus file.', 'https://emrcollege.ac.sz/', 'pdf', 'prospectus'),
  ('Diploma in Occupational Safety and Health - Prospectors', 'Temporary placeholder link. Replace with official prospectus file.', 'https://emrcollege.ac.sz/', 'pdf', 'prospectus')
) AS d(label, description, file_url, file_type, category);

-- 8) Homepage/programme media verified from accessible snapshot
WITH sid AS (
  SELECT id
  FROM schools
  WHERE lower(name) IN (
    lower('Emergency Medical Rescue College'),
    lower('EMR College')
  )
     OR lower(name) LIKE '%emergency medical rescue%'
     OR lower(name) LIKE '%emr college%'
  ORDER BY id
  LIMIT 1
), pg AS (
  SELECT id, slug
  FROM school_pages
  WHERE school_id = (SELECT id FROM sid)
)
INSERT INTO school_media (school_id, page_id, media_type, file_url, alt_text, caption, file_name, mime_type, display_order)
SELECT (SELECT id FROM sid), pg.id, m.media_type, m.file_url, m.alt_text, m.caption, m.file_name, m.mime_type, m.display_order
FROM pg
JOIN (
  VALUES
  ('home', 'image', 'https://emrcollege.ac.sz/wp-content/uploads/2024/04/IMG_8497-scaled.jpg', 'EMR College homepage image', 'Homepage programme image', 'IMG_8497-scaled.jpg', 'image/jpeg', 1),
  ('home', 'image', 'https://emrcollege.ac.sz/wp-content/uploads/2024/04/skills-lab-lectur-9-scaled.jpg', 'Bachelor of Health Science in Emergency Medical Care and Rescue', 'Bachelor of Health Science in Emergency Medical Care and Rescue', 'skills-lab-lectur-9-scaled.jpg', 'image/jpeg', 2),
  ('home', 'image', 'https://emrcollege.ac.sz/wp-content/uploads/2024/04/6-12-scaled.jpg', 'Diploma in Emergency Medical Care and Rescue', 'Diploma in Emergency Medical Care and Rescue', '6-12-scaled.jpg', 'image/jpeg', 3),
  ('home', 'image', 'https://emrcollege.ac.sz/wp-content/uploads/2024/04/skills-lab-lectur-7-scaled.jpg', 'Diploma in Occupational Safety and Health', 'Diploma in Occupational Safety and Health', 'skills-lab-lectur-7-scaled.jpg', 'image/jpeg', 4),
  ('home', 'image', 'https://emrcollege.ac.sz/wp-content/uploads/2024/05/EMRC-2024-NEW-COURSE.-DIPLOMA-IN-RESCUE-TECH.jpg', 'Diploma in Rescue Technology', 'Diploma in Rescue Technology', 'EMRC-2024-NEW-COURSE.-DIPLOMA-IN-RESCUE-TECH.jpg', 'image/jpeg', 5),
  ('home', 'image', 'https://emrcollege.ac.sz/wp-content/uploads/2024/05/EMRC-2024-NEW-COURSE.-DIPLOMA-DISASTER-MANAGEMENT.jpg', 'Diploma in Disaster Management', 'Diploma in Disaster Management', 'EMRC-2024-NEW-COURSE.-DIPLOMA-DISASTER-MANAGEMENT.jpg', 'image/jpeg', 6),
  ('home', 'image', 'https://emrcollege.ac.sz/wp-content/uploads/2024/05/EMRC-2024-NEW-COURSE.-BEAUTY-THERAPY-AESTHETICS.png', 'Diploma in Beauty Therapy and Aesthetics', 'Diploma in Beauty Therapy and Aesthetics', 'EMRC-2024-NEW-COURSE.-BEAUTY-THERAPY-AESTHETICS.png', 'image/png', 7),
  ('home', 'image', 'http://emrcollege.ac.sz/wp-content/uploads/2024/05/EMRC-2024-NEW-COURSE.-DIPLOMA-IN-PUBLIC-HEALTH.png', 'Diploma in Public Health', 'Diploma in Public Health', 'EMRC-2024-NEW-COURSE.-DIPLOMA-IN-PUBLIC-HEALTH.png', 'image/png', 8)
) AS m(page_slug, media_type, file_url, alt_text, caption, file_name, mime_type, display_order)
ON pg.slug = m.page_slug;

-- =============================================================================
-- END
-- =============================================================================