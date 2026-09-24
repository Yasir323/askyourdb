-- =============================================================================
-- 02_seed.sql — deterministic dummy data
--
-- Everything is generated with modular arithmetic over generate_series rather
-- than random(), so re-running this script on an empty database produces
-- byte-identical data. setseed() is called only to pin any future use of
-- random() to a fixed stream.
--
-- Approximate volumes: 500 students, 40 teachers, 254 courses, ~4.6k
-- enrolments, ~1.5k exams, ~27k exam results, ~34k attendance rows,
-- ~1.4k invoices and ~1.2k payments.
-- =============================================================================

SET client_min_messages = warning;
SELECT setseed(0.42);

-- -----------------------------------------------------------------------------
-- Departments
-- -----------------------------------------------------------------------------

INSERT INTO departments (name, code, office_room, annual_budget) VALUES
    ('Mathematics',        'MATH', 'A-101', 185000.00),
    ('Sciences',           'SCI',  'B-204', 312500.00),
    ('Languages',          'LANG', 'A-118', 164000.00),
    ('Humanities',         'HUM',  'C-002', 128750.00),
    ('Arts',               'ARTS', 'D-011',  96400.00),
    ('Physical Education', 'PHED', 'GYM-1',  74250.00),
    ('Computer Science',   'COMP', 'B-310', 241000.00),
    ('Student Affairs',    'STAF', 'A-005',  58900.00);

-- -----------------------------------------------------------------------------
-- Teachers (department heads and mentors are wired up afterwards)
-- -----------------------------------------------------------------------------

INSERT INTO teachers (
    employee_no, first_name, last_name, email, phone,
    date_of_birth, hire_date, department_id, employment, annual_salary
)
SELECT
    'EMP-' || LPAD(n::text, 4, '0'),
    fn.arr[1 + (n * 5) % array_length(fn.arr, 1)],
    ln.arr[1 + (n * 7) % array_length(ln.arr, 1)],
    lower(fn.arr[1 + (n * 5) % array_length(fn.arr, 1)]) || '.'
        || lower(ln.arr[1 + (n * 7) % array_length(ln.arr, 1)]) || n || '@school.example.edu',
    '+1-555-' || LPAD((1000 + n * 17)::text, 4, '0'),
    make_date(1968 + (n * 3) % 30, 1 + (n % 12), 1 + (n % 28)),
    make_date(2005 + (n * 7) % 20, 1 + (n % 9), 1 + (n % 27)),
    1 + (n - 1) % 8,
    (ARRAY['full_time', 'full_time', 'full_time', 'part_time', 'contract', 'visiting']::employment_type[])[1 + n % 6],
    ROUND((48000 + (n * 1373) % 42000)::numeric, 2)
FROM generate_series(1, 40) AS n,
     (SELECT ARRAY[
        'Helen','Samuel','Farida','Gregor','Adaeze','Martin','Ilse','Kwame','Beatriz','Viktor',
        'Nadia','Hugh','Rosalind','Emeka','Clara','Dmitri','Yasmin','Alistair','Meera','Bruno',
        'Ingrid','Theo','Salma']::text[] AS arr) AS fn,
     (SELECT ARRAY[
        'Whitfield','Ostrowski','Balogun','Kaufman','Duarte','Halvorsen','Srinivasan','Cortez',
        'Blackwood','Petrescu','Achebe','Lindgren','Vasilyev','Ferreira','Hollis','Nakashima',
        'Bouchard','Okonkwo','Ramirez','Steiner','Aldridge','Maalouf','Bianchi','Novotny',
        'Sharpe','Eriksen','Chaudhary','Moretti','Langley']::text[] AS arr) AS ln;

-- Longest-serving teacher in each department becomes its head.
UPDATE departments d
   SET head_teacher_id = s.teacher_id
  FROM (
        SELECT DISTINCT ON (department_id) department_id, teacher_id
          FROM teachers
         WHERE department_id IS NOT NULL
         ORDER BY department_id, hire_date, teacher_id
       ) AS s
 WHERE s.department_id = d.department_id;

-- Two thirds of teachers get a more senior mentor from their own department.
UPDATE teachers t
   SET mentor_teacher_id = s.mentor_id
  FROM (
        SELECT DISTINCT ON (junior.teacher_id)
               junior.teacher_id,
               senior.teacher_id AS mentor_id
          FROM teachers AS junior
          JOIN teachers AS senior
            ON senior.department_id = junior.department_id
           AND senior.teacher_id   <> junior.teacher_id
           AND senior.hire_date     < junior.hire_date
         ORDER BY junior.teacher_id, senior.hire_date, senior.teacher_id
       ) AS s
 WHERE s.teacher_id = t.teacher_id
   AND t.teacher_id % 3 <> 0;

-- -----------------------------------------------------------------------------
-- Subjects
-- -----------------------------------------------------------------------------

INSERT INTO subjects (code, name, department_id, credit_hours, is_elective, description) VALUES
    ('MATH101', 'Mathematics',          1, 4, FALSE, 'Core mathematics for all grade levels.'),
    ('MATH201', 'Advanced Mathematics', 1, 5, TRUE,  'Calculus and linear algebra for senior grades.'),
    ('SCI101',  'General Science',      2, 3, FALSE, 'Integrated science for primary and middle school.'),
    ('SCI201',  'Physics',              2, 4, FALSE, 'Mechanics, waves, electricity and magnetism.'),
    ('SCI202',  'Chemistry',            2, 4, FALSE, 'Atomic structure, bonding and reactions.'),
    ('SCI203',  'Biology',              2, 4, FALSE, 'Cells, genetics, physiology and ecology.'),
    ('LANG101', 'English Language',     3, 4, FALSE, 'Reading, writing and oral communication.'),
    ('LANG102', 'English Literature',   3, 3, FALSE, 'Prose, poetry and drama.'),
    ('LANG201', 'French',               3, 2, TRUE,  'Second language option.'),
    ('LANG202', 'Spanish',              3, 2, TRUE,  'Second language option.'),
    ('HUM101',  'History',              4, 3, FALSE, 'World and regional history.'),
    ('HUM102',  'Geography',            4, 3, FALSE, 'Physical and human geography.'),
    ('HUM201',  'Economics',            4, 3, TRUE,  'Micro and macroeconomics for senior grades.'),
    ('ARTS101', 'Visual Arts',          5, 2, FALSE, 'Drawing, painting and design.'),
    ('ARTS102', 'Music',                5, 2, FALSE, 'Theory, voice and instrumental practice.'),
    ('PHED101', 'Physical Education',   6, 2, FALSE, 'Fitness, athletics and team sport.'),
    ('COMP101', 'Computing',            7, 3, FALSE, 'Digital literacy and introductory programming.'),
    ('COMP201', 'Software Design',      7, 4, TRUE,  'Algorithms, data structures and project work.');

-- -----------------------------------------------------------------------------
-- Academic years, terms and grade levels
-- -----------------------------------------------------------------------------

INSERT INTO academic_years (name, start_date, end_date, is_current) VALUES
    ('2024-2025', DATE '2024-08-19', DATE '2025-06-13', FALSE),
    ('2025-2026', DATE '2025-08-18', DATE '2026-06-12', TRUE);

INSERT INTO terms (academic_year_id, name, term_number, start_date, end_date)
SELECT ay.academic_year_id,
       (ARRAY['Autumn Term', 'Spring Term', 'Summer Term'])[k],
       k,
       ay.start_date + (k - 1) * 98,
       CASE WHEN k = 3 THEN ay.end_date ELSE ay.start_date + (k - 1) * 98 + 95 END
  FROM academic_years AS ay,
       generate_series(1, 3) AS k;

INSERT INTO grade_levels (level_number, label, stage)
SELECT n,
       'Grade ' || n,
       CASE WHEN n <= 5 THEN 'primary' WHEN n <= 8 THEN 'middle' ELSE 'secondary' END
  FROM generate_series(1, 12) AS n;

-- -----------------------------------------------------------------------------
-- Class sections: A and B for every grade, plus C for grades 9-12.
-- -----------------------------------------------------------------------------

INSERT INTO class_sections (academic_year_id, grade_level_id, section_label, room_number, capacity)
SELECT ay.academic_year_id,
       gl.grade_level_id,
       s.label,
       CASE WHEN gl.level_number <= 5 THEN 'P' WHEN gl.level_number <= 8 THEN 'M' ELSE 'S' END
           || '-' || LPAD(gl.level_number::text, 2, '0') || s.label,
       CASE WHEN gl.level_number <= 5 THEN 26 ELSE 32 END
  FROM academic_years AS ay
 CROSS JOIN grade_levels AS gl
 CROSS JOIN (VALUES ('A'), ('B'), ('C')) AS s (label)
 WHERE s.label <> 'C' OR gl.level_number >= 9;

UPDATE class_sections cs
   SET homeroom_teacher_id = t.teacher_id
  FROM (
        SELECT teacher_id,
               ROW_NUMBER() OVER (ORDER BY teacher_id) - 1 AS idx,
               COUNT(*)     OVER ()                        AS total
          FROM teachers
       ) AS t
 WHERE t.idx = (cs.class_section_id * 7) % t.total;

-- -----------------------------------------------------------------------------
-- Students: 500, spread evenly across the current year's sections.
-- -----------------------------------------------------------------------------

WITH current_sections AS (
    SELECT cs.class_section_id,
           gl.level_number,
           ROW_NUMBER() OVER (ORDER BY gl.level_number, cs.section_label) - 1 AS idx,
           COUNT(*)     OVER ()                                                AS total
      FROM class_sections AS cs
      JOIN grade_levels   AS gl ON gl.grade_level_id = cs.grade_level_id
      JOIN academic_years AS ay ON ay.academic_year_id = cs.academic_year_id
     WHERE ay.is_current
),
names AS (
    SELECT ARRAY[
        'Aisha','Liam','Noor','Mateo','Zara','Ethan','Priya','Omar','Sofia','Hana',
        'Lucas','Amina','Kai','Elena','Rohan','Maya','Diego','Yusuf','Chloe','Arjun',
        'Leila','Noah','Ines','Tariq','Anika','Felix','Mira','Sebastian','Nadia','Oscar',
        'Sana','Emil','Lucia','Idris','Freya','Jonas','Aaliyah','Marco','Thea','Rafael',
        'Zainab']::text[] AS first_names,
        ARRAY[
        'Okafor','Nguyen','Kowalski','Rahman','Silva','Andersen','Mehta','Haddad','Fernandez','Novak',
        'Iyer','Bekele','Castillo','Petrov','Larsen','Osei','Dubois','Kimura','Almeida','Farah',
        'Weber','Chowdhury','Moreau','Sandoval','Ivanov','Tanaka','Baptiste','Grimaldi','Villanueva','Zhukov',
        'Adeyemi','Lindqvist','Barros','Qureshi','Marchetti','Delgado','Hoffmann','Nakamura','Abadi','Rossi',
        'Escobar','Vasquez','Bergstrom']::text[] AS last_names,
        ARRAY[
        'Riverton','Ashgrove','Kingsport','Elmsdale','Northfield','Westbrook',
        'Fairhaven','Stonebridge','Marlow','Brightwater','Hollowfield','Cedarvale']::text[] AS cities,
        ARRAY[
        'Maple Street','Cedar Lane','Willow Road','Birch Avenue','Ashfield Way','Harbour Drive',
        'Orchard Close','Fern Hollow','Bridge Street','Quarry Road','Lantern Walk','Meadow Rise',
        'Chapel Row','Old Mill Lane','Sycamore Court']::text[] AS streets
)
INSERT INTO students (
    admission_no, first_name, last_name, date_of_birth, gender, email, phone,
    address_line, city, postal_code, admission_date, status, current_class_section_id
)
SELECT
    'ADM-2025-' || LPAD(n::text, 4, '0'),
    nm.first_names[1 + (n * 7)  % array_length(nm.first_names, 1)],
    nm.last_names [1 + (n * 11) % array_length(nm.last_names,  1)],
    make_date(2025 - 5 - cs.level_number, 1 + (n % 12), 1 + (n % 28)),
    (ARRAY['female', 'male', 'female', 'male', 'other', 'undisclosed']::gender_type[])[1 + n % 6],
    lower(nm.first_names[1 + (n * 7)  % array_length(nm.first_names, 1)]) || '.'
        || lower(nm.last_names[1 + (n * 11) % array_length(nm.last_names, 1)]) || n || '@student.example.edu',
    '+1-555-' || LPAD((2000 + n * 3)::text, 4, '0'),
    (100 + (n * 13) % 890)::text || ' ' || nm.streets[1 + (n * 5) % array_length(nm.streets, 1)],
    nm.cities[1 + (n * 3) % array_length(nm.cities, 1)],
    LPAD(((n * 137) % 90000 + 10000)::text, 5, '0'),
    (DATE '2025-08-15' - (cs.level_number - 1) * 365)::date,
    (CASE WHEN n % 97 = 0 THEN 'withdrawn'
          WHEN n % 89 = 0 THEN 'transferred'
          WHEN n % 83 = 0 THEN 'suspended'
          ELSE 'active' END)::student_status,
    cs.class_section_id
  FROM generate_series(1, 500) AS n
 CROSS JOIN names AS nm
  JOIN current_sections AS cs ON cs.idx = (n - 1) % cs.total;

-- -----------------------------------------------------------------------------
-- Guardians: one primary per student, plus a second for every third student.
-- The student id is smuggled through the email address so the junction rows
-- can be written in the same statement without relying on insertion order.
-- -----------------------------------------------------------------------------

WITH guardian_names AS (
    SELECT ARRAY[
        'Maryam','David','Ngozi','Peter','Sunita','Karim','Elena','Joseph','Fatima','Michael',
        'Lucia','Ahmed','Grace','Stefan','Rania','Paul','Anjali','Victor','Hannah','Mustafa',
        'Camila','Andrei','Yuki','Daniel','Zahra','Henrik','Beatrice','Samir','Olga','Tomas',
        'Layla']::text[] AS first_names,
        ARRAY[
        'Accountant','Nurse','Civil Engineer','Shopkeeper','Teacher','Software Developer',
        'Electrician','Pharmacist','Bus Driver','Architect','Chef','Paramedic',
        'Journalist','Farmer','Logistics Manager']::text[] AS jobs
),
inserted AS (
    INSERT INTO guardians (first_name, last_name, email, phone, occupation, address_line, city)
    SELECT gn.first_names[1 + (s.student_id * 3) % array_length(gn.first_names, 1)],
           s.last_name,
           'g1.' || s.student_id || '@guardian.example.com',
           '+1-555-' || LPAD((3000 + s.student_id * 7)::text, 4, '0'),
           gn.jobs[1 + (s.student_id * 5) % array_length(gn.jobs, 1)],
           s.address_line,
           s.city
      FROM students AS s
     CROSS JOIN guardian_names AS gn
    RETURNING guardian_id, email
)
INSERT INTO student_guardians (student_id, guardian_id, relationship, is_primary)
SELECT split_part(split_part(i.email, '@', 1), '.', 2)::int,
       i.guardian_id,
       (CASE WHEN split_part(split_part(i.email, '@', 1), '.', 2)::int % 2 = 0
             THEN 'mother' ELSE 'father' END)::guardian_relationship,
       TRUE
  FROM inserted AS i;

WITH guardian_names AS (
    SELECT ARRAY[
        'Robert','Amara','Tobias','Neha','Franco','Selma','Ibrahim','Marta','Erik','Chidi',
        'Pilar','Noel','Rasha','Gustav','Divya','Alban','Mona']::text[] AS first_names
),
inserted AS (
    INSERT INTO guardians (first_name, last_name, email, phone, occupation, address_line, city)
    SELECT gn.first_names[1 + (s.student_id * 7) % array_length(gn.first_names, 1)],
           s.last_name,
           'g2.' || s.student_id || '@guardian.example.com',
           '+1-555-' || LPAD((6000 + s.student_id * 11)::text, 4, '0'),
           'Retired',
           s.address_line,
           s.city
      FROM students AS s
     CROSS JOIN guardian_names AS gn
     WHERE s.student_id % 3 = 0
    RETURNING guardian_id, email
)
INSERT INTO student_guardians (student_id, guardian_id, relationship, is_primary)
SELECT split_part(split_part(i.email, '@', 1), '.', 2)::int,
       i.guardian_id,
       (CASE WHEN split_part(split_part(i.email, '@', 1), '.', 2)::int % 4 = 0
             THEN 'grandparent' ELSE 'legal_guardian' END)::guardian_relationship,
       FALSE
  FROM inserted AS i;

-- -----------------------------------------------------------------------------
-- Courses: a grade-appropriate subject list per section of the current year,
-- taught by a teacher drawn from the subject's own department.
-- -----------------------------------------------------------------------------

INSERT INTO courses (subject_id, class_section_id, teacher_id, weekly_periods, room_number)
SELECT s.subject_id,
       cs.class_section_id,
       tl.teacher_id,
       CASE WHEN s.is_elective THEN 2 ELSE 4 END,
       cs.room_number
  FROM class_sections  AS cs
  JOIN academic_years  AS ay ON ay.academic_year_id = cs.academic_year_id AND ay.is_current
  JOIN grade_levels    AS gl ON gl.grade_level_id   = cs.grade_level_id
  JOIN subjects        AS s
    ON (gl.level_number <= 5
        AND s.code IN ('MATH101', 'SCI101', 'LANG101', 'HUM101', 'HUM102', 'ARTS101', 'ARTS102', 'PHED101'))
    OR (gl.level_number BETWEEN 6 AND 8
        AND s.code IN ('MATH101', 'SCI101', 'LANG101', 'LANG102', 'HUM101', 'HUM102', 'ARTS101', 'PHED101', 'COMP101'))
    OR (gl.level_number >= 9
        AND s.code IN ('MATH101', 'MATH201', 'SCI201', 'SCI202', 'SCI203', 'LANG101', 'LANG102', 'HUM101', 'PHED101', 'COMP201'))
  LEFT JOIN LATERAL (
        SELECT te.teacher_id
          FROM teachers AS te
         WHERE te.department_id = s.department_id
           AND te.is_active
         ORDER BY (te.teacher_id * 7 + cs.class_section_id * 13) % 97, te.teacher_id
         LIMIT 1
       ) AS tl ON TRUE;

-- -----------------------------------------------------------------------------
-- Enrolments: every student takes every course offered to their section.
-- -----------------------------------------------------------------------------

INSERT INTO enrollments (student_id, course_id, enrolled_on, status)
SELECT st.student_id,
       c.course_id,
       ay.start_date,
       'enrolled'
  FROM students       AS st
  JOIN courses        AS c  ON c.class_section_id   = st.current_class_section_id
  JOIN class_sections AS cs ON cs.class_section_id  = c.class_section_id
  JOIN academic_years AS ay ON ay.academic_year_id  = cs.academic_year_id;

-- -----------------------------------------------------------------------------
-- Grading scale
-- -----------------------------------------------------------------------------

INSERT INTO grade_scale (letter, min_percent, max_percent, gpa_points, is_passing) VALUES
    ('A+', 97.00, 100.00, 4.00, TRUE),
    ('A',  93.00,  96.99, 4.00, TRUE),
    ('A-', 90.00,  92.99, 3.70, TRUE),
    ('B+', 87.00,  89.99, 3.30, TRUE),
    ('B',  83.00,  86.99, 3.00, TRUE),
    ('B-', 80.00,  82.99, 2.70, TRUE),
    ('C+', 77.00,  79.99, 2.30, TRUE),
    ('C',  73.00,  76.99, 2.00, TRUE),
    ('C-', 70.00,  72.99, 1.70, TRUE),
    ('D',  60.00,  69.99, 1.00, TRUE),
    ('F',   0.00,  59.99, 0.00, FALSE);

-- -----------------------------------------------------------------------------
-- Exams: one quiz and one end-of-term paper per course per term.
-- -----------------------------------------------------------------------------

INSERT INTO exams (course_id, term_id, title, exam_type, exam_date, max_score, weight_percent)
SELECT c.course_id,
       t.term_id,
       CASE k WHEN 1 THEN 'Class Quiz - ' || t.name ELSE 'End of Term Exam - ' || t.name END,
       (CASE WHEN k = 1 THEN 'quiz'
             WHEN t.term_number = 3 THEN 'final'
             ELSE 'midterm' END)::exam_type,
       CASE k WHEN 1 THEN t.start_date + 30 ELSE t.end_date - 5 END,
       CASE k WHEN 1 THEN 20 ELSE 100 END,
       CASE k WHEN 1 THEN 30 ELSE 70 END
  FROM courses         AS c
  JOIN class_sections  AS cs ON cs.class_section_id  = c.class_section_id
  JOIN academic_years  AS ay ON ay.academic_year_id  = cs.academic_year_id AND ay.is_current
  JOIN terms           AS t  ON t.academic_year_id   = ay.academic_year_id
 CROSS JOIN generate_series(1, 2) AS k;

-- -----------------------------------------------------------------------------
-- Exam results: one row per enrolled student per exam. Roughly 2% are absent.
-- -----------------------------------------------------------------------------

INSERT INTO exam_results (exam_id, student_id, score, is_absent, graded_by, graded_at, remarks)
SELECT e.exam_id,
       en.student_id,
       CASE WHEN (en.student_id * 37 + e.exam_id * 11) % 53 = 0
            THEN NULL
            ELSE ROUND(e.max_score * (0.52 + ((en.student_id * 17 + e.exam_id * 29) % 45)::numeric / 100), 2)
       END,
       (en.student_id * 37 + e.exam_id * 11) % 53 = 0,
       c.teacher_id,
       (e.exam_date + 3)::timestamptz + INTERVAL '17 hours',
       CASE WHEN (en.student_id * 37 + e.exam_id * 11) % 53 = 0  THEN 'Absent from assessment.'
            WHEN (en.student_id * 17 + e.exam_id * 29) % 45 > 41 THEN 'Excellent work, keep it up.'
            WHEN (en.student_id * 17 + e.exam_id * 29) % 45 < 4  THEN 'Needs improvement - see me.'
            ELSE NULL
       END
  FROM exams       AS e
  JOIN courses     AS c  ON c.course_id  = e.course_id
  JOIN enrollments AS en ON en.course_id = c.course_id;

-- Roll exam scores up into a weighted final score per enrolment.
UPDATE enrollments en
   SET final_score = x.average_percent
  FROM (
        SELECT er.student_id,
               e.course_id,
               ROUND(
                   SUM(er.score / e.max_score * 100 * e.weight_percent) / SUM(e.weight_percent),
               2) AS average_percent
          FROM exam_results AS er
          JOIN exams        AS e ON e.exam_id = er.exam_id
         WHERE er.score IS NOT NULL
         GROUP BY er.student_id, e.course_id
       ) AS x
 WHERE x.student_id = en.student_id
   AND x.course_id  = en.course_id;

-- -----------------------------------------------------------------------------
-- Attendance: weekdays of the current year's first term only.
-- -----------------------------------------------------------------------------

INSERT INTO attendance (student_id, class_section_id, attendance_date, status, recorded_by, note)
SELECT st.student_id,
       cs.class_section_id,
       d::date,
       (CASE
          WHEN (st.student_id * 13 + (d::date - t.start_date) * 7) % 61 = 0 THEN 'absent'
          WHEN (st.student_id * 13 + (d::date - t.start_date) * 7) % 37 = 0 THEN 'late'
          WHEN (st.student_id * 13 + (d::date - t.start_date) * 7) % 89 = 0 THEN 'excused'
          ELSE 'present'
        END)::attendance_status,
       cs.homeroom_teacher_id,
       CASE WHEN (st.student_id * 13 + (d::date - t.start_date) * 7) % 89 = 0
            THEN 'Prior notice from guardian.' END
  FROM students       AS st
  JOIN class_sections AS cs ON cs.class_section_id = st.current_class_section_id
 CROSS JOIN terms     AS t
 CROSS JOIN LATERAL generate_series(t.start_date, t.end_date, INTERVAL '1 day') AS d
 WHERE t.term_number = 1
   AND t.academic_year_id = (SELECT academic_year_id FROM academic_years WHERE is_current)
   AND EXTRACT(ISODOW FROM d) < 6;

-- -----------------------------------------------------------------------------
-- Extracurricular activities
-- -----------------------------------------------------------------------------

INSERT INTO activities (name, category, meeting_day, meeting_time, location, max_participants, annual_fee) VALUES
    ('Football Club',        'sports',     'Monday',    TIME '15:30', 'Main Field',      36, 120.00),
    ('Basketball Team',      'sports',     'Tuesday',   TIME '16:00', 'Gymnasium',       24, 140.00),
    ('Swimming Squad',       'sports',     'Thursday',  TIME '07:00', 'Pool',            20, 260.00),
    ('Debate Society',       'academic',   'Wednesday', TIME '15:00', 'Room C-002',      30,  40.00),
    ('Robotics Club',        'technology', 'Friday',    TIME '15:30', 'Lab B-310',       18, 190.00),
    ('Coding Circle',        'technology', 'Tuesday',   TIME '15:30', 'Lab B-311',       24,  60.00),
    ('School Orchestra',     'music',      'Wednesday', TIME '16:30', 'Music Hall',      45, 150.00),
    ('Choir',                'music',      'Monday',    TIME '16:00', 'Music Hall',      60,  35.00),
    ('Drama Guild',          'arts',       'Thursday',  TIME '15:30', 'Auditorium',      32,  75.00),
    ('Photography Club',     'arts',       'Friday',    TIME '14:30', 'Room D-011',      16,  95.00),
    ('Community Volunteers', 'service',    'Saturday',  TIME '09:00', 'Assembly Hall',   50,   0.00),
    ('Model United Nations', 'academic',   'Friday',    TIME '16:00', 'Room C-004',      28,  55.00);

UPDATE activities a
   SET coordinator_teacher_id = t.teacher_id
  FROM (
        SELECT teacher_id,
               ROW_NUMBER() OVER (ORDER BY teacher_id) - 1 AS idx,
               COUNT(*)     OVER ()                        AS total
          FROM teachers
         WHERE is_active
       ) AS t
 WHERE t.idx = (a.activity_id * 11) % t.total;

-- Four fifths of students join one activity...
INSERT INTO activity_participants (student_id, activity_id, joined_on, role, is_active)
SELECT st.student_id,
       a.activity_id,
       ay.start_date + 14,
       CASE WHEN st.student_id % 23 = 0 THEN 'captain'
            WHEN st.student_id % 11 = 0 THEN 'secretary'
            ELSE 'member' END,
       TRUE
  FROM students       AS st
 CROSS JOIN academic_years AS ay
  JOIN LATERAL (
        SELECT activity_id
          FROM activities
         ORDER BY (activity_id * 31 + st.student_id * 17) % 101, activity_id
         LIMIT 1
       ) AS a ON TRUE
 WHERE ay.is_current
   AND st.student_id % 5 <> 0
ON CONFLICT DO NOTHING;

-- ...and every third student joins a second one.
INSERT INTO activity_participants (student_id, activity_id, joined_on, role, is_active)
SELECT st.student_id,
       a.activity_id,
       ay.start_date + 35,
       'member',
       st.student_id % 7 <> 0
  FROM students       AS st
 CROSS JOIN academic_years AS ay
  JOIN LATERAL (
        SELECT activity_id
          FROM activities
         ORDER BY (activity_id * 13 + st.student_id * 41) % 97, activity_id
         LIMIT 1
       ) AS a ON TRUE
 WHERE ay.is_current
   AND st.student_id % 3 = 0
ON CONFLICT DO NOTHING;

-- -----------------------------------------------------------------------------
-- Fees: one invoice per active student per term of the current year.
-- -----------------------------------------------------------------------------

INSERT INTO fee_types (code, name, default_amount, is_recurring, description) VALUES
    ('TUITION',   'Tuition Fee',            1850.00, TRUE,  'Charged once per term.'),
    ('LIBRARY',   'Library and Resources',    65.00, TRUE,  'Books, e-resources and printing allowance.'),
    ('EXAM',      'Examination Fee',          90.00, TRUE,  'Term assessment administration.'),
    ('TRANSPORT', 'School Transport',        320.00, TRUE,  'Door-to-door bus service, opt-in.'),
    ('LAB',       'Laboratory Fee',          145.00, TRUE,  'Science practical consumables, grades 9-12.'),
    ('SPORTS',    'Sports Facilities',        110.00, TRUE,  'Access to gymnasium, pool and pitches.'),
    ('UNIFORM',   'Uniform and Kit',         240.00, FALSE, 'Charged in the first term only.'),
    ('ACTIVITY',  'Extracurricular Levy',     75.00, FALSE, 'Charged in the first term to club members.');

INSERT INTO invoices (invoice_no, student_id, academic_year_id, term_id, issue_date, due_date, total_amount, status)
SELECT 'INV-' || to_char(t.start_date, 'YYYY') || '-'
           || LPAD((ROW_NUMBER() OVER (ORDER BY s.student_id, t.term_number))::text, 5, '0'),
       s.student_id,
       t.academic_year_id,
       t.term_id,
       t.start_date,
       t.start_date + 30,
       0,
       'issued'
  FROM students AS s
  JOIN terms    AS t
    ON t.academic_year_id = (SELECT academic_year_id FROM academic_years WHERE is_current)
 WHERE s.status = 'active';

INSERT INTO invoice_items (invoice_id, fee_type_id, description, quantity, unit_amount)
SELECT i.invoice_id,
       ft.fee_type_id,
       ft.name || ' - ' || t.name,
       1,
       ROUND(ft.default_amount * CASE WHEN gl.level_number >= 9 THEN 1.15
                                      WHEN gl.level_number >= 6 THEN 1.05
                                      ELSE 1.00 END, 2)
  FROM invoices       AS i
  JOIN terms          AS t  ON t.term_id           = i.term_id
  JOIN students       AS s  ON s.student_id        = i.student_id
  JOIN class_sections AS cs ON cs.class_section_id = s.current_class_section_id
  JOIN grade_levels   AS gl ON gl.grade_level_id   = cs.grade_level_id
  JOIN fee_types      AS ft
    ON ft.code IN ('TUITION', 'LIBRARY', 'EXAM')
    OR (ft.code = 'TRANSPORT' AND s.student_id % 5 < 2)
    OR (ft.code = 'LAB'       AND gl.level_number >= 9)
    OR (ft.code = 'SPORTS'    AND s.student_id % 3 = 0)
    OR (ft.code = 'UNIFORM'   AND t.term_number = 1)
    OR (ft.code = 'ACTIVITY'  AND t.term_number = 1
        AND EXISTS (SELECT 1 FROM activity_participants AS ap WHERE ap.student_id = s.student_id));

UPDATE invoices i
   SET total_amount = x.total
  FROM (SELECT invoice_id, SUM(line_total) AS total FROM invoice_items GROUP BY invoice_id) AS x
 WHERE x.invoice_id = i.invoice_id;

-- 70% of invoices are settled in full, 15% partially, 15% not at all.
INSERT INTO payments (invoice_id, paid_on, amount, method, reference_no, received_by, note)
SELECT i.invoice_id,
       i.issue_date + (i.invoice_id % 34),
       CASE WHEN i.invoice_id % 20 < 14 THEN i.total_amount
            ELSE ROUND(i.total_amount * 0.55, 2) END,
       (ARRAY['bank_transfer', 'online', 'card', 'cash', 'cheque']::payment_method[])[1 + i.invoice_id % 5],
       'PAY-' || LPAD(i.invoice_id::text, 6, '0'),
       'Bursar Office',
       CASE WHEN i.invoice_id % 20 >= 14 THEN 'Partial payment, balance pending.' END
  FROM invoices AS i
 WHERE i.invoice_id % 20 < 17
   AND i.total_amount > 0;

UPDATE invoices i
   SET status = (CASE WHEN x.paid >= i.total_amount    THEN 'paid'
                      WHEN x.paid > 0                  THEN 'partially_paid'
                      WHEN i.due_date < CURRENT_DATE   THEN 'overdue'
                      ELSE 'issued' END)::invoice_status
  FROM (
        SELECT i2.invoice_id, COALESCE(SUM(p.amount), 0) AS paid
          FROM invoices AS i2
          LEFT JOIN payments AS p ON p.invoice_id = i2.invoice_id
         GROUP BY i2.invoice_id
       ) AS x
 WHERE x.invoice_id = i.invoice_id;

ANALYZE;
