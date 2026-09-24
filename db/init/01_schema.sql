-- =============================================================================
-- 01_schema.sql — School management schema
--
-- 22 tables across 7 domains. Deliberately includes a self-referencing FK,
-- a circular FK pair, composite primary keys, native enums, a generated
-- column and a partial unique index so that schema-introspection tooling
-- has something non-trivial to reflect.
-- =============================================================================

SET client_min_messages = warning;

-- -----------------------------------------------------------------------------
-- Enumerated types
-- -----------------------------------------------------------------------------

CREATE TYPE gender_type            AS ENUM ('male', 'female', 'other', 'undisclosed');
CREATE TYPE employment_type        AS ENUM ('full_time', 'part_time', 'contract', 'visiting');
CREATE TYPE student_status         AS ENUM ('active', 'graduated', 'transferred', 'withdrawn', 'suspended');
CREATE TYPE enrollment_status      AS ENUM ('enrolled', 'completed', 'dropped');
CREATE TYPE guardian_relationship  AS ENUM ('mother', 'father', 'grandparent', 'sibling', 'legal_guardian', 'other');
CREATE TYPE exam_type              AS ENUM ('quiz', 'midterm', 'final', 'practical', 'project');
CREATE TYPE attendance_status      AS ENUM ('present', 'absent', 'late', 'excused');
CREATE TYPE activity_category      AS ENUM ('sports', 'arts', 'academic', 'service', 'music', 'technology');
CREATE TYPE invoice_status         AS ENUM ('draft', 'issued', 'partially_paid', 'paid', 'overdue', 'cancelled');
CREATE TYPE payment_method         AS ENUM ('cash', 'card', 'bank_transfer', 'cheque', 'online');

-- =============================================================================
-- Domain 1: Organisation
-- =============================================================================

CREATE TABLE departments (
    department_id   SERIAL PRIMARY KEY,
    name            VARCHAR(80)  NOT NULL UNIQUE,
    code            VARCHAR(6)   NOT NULL UNIQUE,
    -- FK to teachers is added after that table exists (circular reference).
    head_teacher_id INTEGER,
    office_room     VARCHAR(20),
    annual_budget   NUMERIC(12, 2) CHECK (annual_budget >= 0),
    created_at      TIMESTAMPTZ  NOT NULL DEFAULT now()
);

COMMENT ON TABLE departments IS 'Academic and administrative departments of the school.';

CREATE TABLE teachers (
    teacher_id        SERIAL PRIMARY KEY,
    employee_no       VARCHAR(12)  NOT NULL UNIQUE,
    first_name        VARCHAR(60)  NOT NULL,
    last_name         VARCHAR(60)  NOT NULL,
    email             VARCHAR(120) NOT NULL UNIQUE,
    phone             VARCHAR(25),
    date_of_birth     DATE,
    hire_date         DATE         NOT NULL,
    department_id     INTEGER      REFERENCES departments (department_id) ON DELETE SET NULL,
    -- Self-referencing FK: every junior teacher is mentored by a senior one.
    mentor_teacher_id INTEGER      REFERENCES teachers (teacher_id) ON DELETE SET NULL,
    employment        employment_type NOT NULL DEFAULT 'full_time',
    annual_salary     NUMERIC(10, 2) CHECK (annual_salary > 0),
    is_active         BOOLEAN      NOT NULL DEFAULT TRUE,
    CONSTRAINT teachers_no_self_mentor CHECK (mentor_teacher_id IS DISTINCT FROM teacher_id)
);

COMMENT ON COLUMN teachers.mentor_teacher_id IS 'Self-referencing FK to a more senior teacher.';

-- Closes the departments <-> teachers cycle. Deferrable so both sides can be
-- written inside a single transaction without ordering games.
ALTER TABLE departments
    ADD CONSTRAINT departments_head_teacher_fk
    FOREIGN KEY (head_teacher_id) REFERENCES teachers (teacher_id) ON DELETE SET NULL
    DEFERRABLE INITIALLY DEFERRED;

CREATE TABLE subjects (
    subject_id    SERIAL PRIMARY KEY,
    code          VARCHAR(10) NOT NULL UNIQUE,
    name          VARCHAR(80) NOT NULL,
    department_id INTEGER     NOT NULL REFERENCES departments (department_id),
    credit_hours  SMALLINT    NOT NULL DEFAULT 1 CHECK (credit_hours BETWEEN 1 AND 6),
    is_elective   BOOLEAN     NOT NULL DEFAULT FALSE,
    description   TEXT
);

-- =============================================================================
-- Domain 2: Academic structure
-- =============================================================================

CREATE TABLE academic_years (
    academic_year_id SERIAL PRIMARY KEY,
    name             VARCHAR(9) NOT NULL UNIQUE,   -- e.g. '2025-2026'
    start_date       DATE       NOT NULL,
    end_date         DATE       NOT NULL,
    is_current       BOOLEAN    NOT NULL DEFAULT FALSE,
    CONSTRAINT academic_years_date_order CHECK (end_date > start_date)
);

-- Partial unique index: at most one year may be flagged as current.
CREATE UNIQUE INDEX academic_years_single_current
    ON academic_years (is_current) WHERE is_current;

CREATE TABLE terms (
    term_id          SERIAL PRIMARY KEY,
    academic_year_id INTEGER     NOT NULL REFERENCES academic_years (academic_year_id) ON DELETE CASCADE,
    name             VARCHAR(30) NOT NULL,
    term_number      SMALLINT    NOT NULL CHECK (term_number BETWEEN 1 AND 4),
    start_date       DATE        NOT NULL,
    end_date         DATE        NOT NULL,
    CONSTRAINT terms_date_order   CHECK (end_date > start_date),
    CONSTRAINT terms_unique_number UNIQUE (academic_year_id, term_number)
);

CREATE TABLE grade_levels (
    grade_level_id SERIAL PRIMARY KEY,
    level_number   SMALLINT    NOT NULL UNIQUE CHECK (level_number BETWEEN 1 AND 12),
    label          VARCHAR(20) NOT NULL,
    stage          VARCHAR(20) NOT NULL CHECK (stage IN ('primary', 'middle', 'secondary'))
);

CREATE TABLE class_sections (
    class_section_id    SERIAL PRIMARY KEY,
    academic_year_id    INTEGER  NOT NULL REFERENCES academic_years (academic_year_id),
    grade_level_id      INTEGER  NOT NULL REFERENCES grade_levels (grade_level_id),
    section_label       CHAR(1)  NOT NULL,
    homeroom_teacher_id INTEGER  REFERENCES teachers (teacher_id) ON DELETE SET NULL,
    room_number         VARCHAR(10),
    capacity            SMALLINT NOT NULL DEFAULT 30 CHECK (capacity > 0),
    CONSTRAINT class_sections_unique UNIQUE (academic_year_id, grade_level_id, section_label)
);

COMMENT ON TABLE class_sections IS 'One homeroom group, e.g. Grade 9 section B in 2025-2026.';

-- =============================================================================
-- Domain 3: People
-- =============================================================================

CREATE TABLE students (
    student_id               SERIAL PRIMARY KEY,
    admission_no             VARCHAR(15)  NOT NULL UNIQUE,
    first_name               VARCHAR(60)  NOT NULL,
    last_name                VARCHAR(60)  NOT NULL,
    date_of_birth            DATE         NOT NULL,
    gender                   gender_type  NOT NULL DEFAULT 'undisclosed',
    email                    VARCHAR(120) UNIQUE,
    phone                    VARCHAR(25),
    address_line             VARCHAR(160),
    city                     VARCHAR(60),
    postal_code              VARCHAR(12),
    admission_date           DATE         NOT NULL,
    status                   student_status NOT NULL DEFAULT 'active',
    current_class_section_id INTEGER      REFERENCES class_sections (class_section_id) ON DELETE SET NULL,
    created_at               TIMESTAMPTZ  NOT NULL DEFAULT now()
);

CREATE TABLE guardians (
    guardian_id  SERIAL PRIMARY KEY,
    first_name   VARCHAR(60)  NOT NULL,
    last_name    VARCHAR(60)  NOT NULL,
    email        VARCHAR(120),
    phone        VARCHAR(25)  NOT NULL,
    occupation   VARCHAR(80),
    address_line VARCHAR(160),
    city         VARCHAR(60)
);

-- Composite PK junction.
CREATE TABLE student_guardians (
    student_id   INTEGER NOT NULL REFERENCES students (student_id)   ON DELETE CASCADE,
    guardian_id  INTEGER NOT NULL REFERENCES guardians (guardian_id) ON DELETE CASCADE,
    relationship guardian_relationship NOT NULL,
    is_primary   BOOLEAN NOT NULL DEFAULT FALSE,
    PRIMARY KEY (student_id, guardian_id)
);

-- =============================================================================
-- Domain 4: Courses and enrolment
-- =============================================================================

CREATE TABLE courses (
    course_id        SERIAL PRIMARY KEY,
    subject_id       INTEGER  NOT NULL REFERENCES subjects (subject_id),
    class_section_id INTEGER  NOT NULL REFERENCES class_sections (class_section_id) ON DELETE CASCADE,
    teacher_id       INTEGER  REFERENCES teachers (teacher_id) ON DELETE SET NULL,
    weekly_periods   SMALLINT NOT NULL DEFAULT 4 CHECK (weekly_periods BETWEEN 1 AND 10),
    room_number      VARCHAR(10),
    CONSTRAINT courses_unique UNIQUE (class_section_id, subject_id)
);

COMMENT ON TABLE courses IS 'One subject taught to one class section by one teacher.';

-- Composite PK junction.
CREATE TABLE enrollments (
    student_id  INTEGER NOT NULL REFERENCES students (student_id) ON DELETE CASCADE,
    course_id   INTEGER NOT NULL REFERENCES courses (course_id)   ON DELETE CASCADE,
    enrolled_on DATE    NOT NULL DEFAULT CURRENT_DATE,
    status      enrollment_status NOT NULL DEFAULT 'enrolled',
    final_score NUMERIC(5, 2) CHECK (final_score BETWEEN 0 AND 100),
    PRIMARY KEY (student_id, course_id)
);

-- =============================================================================
-- Domain 5: Assessment
-- =============================================================================

CREATE TABLE grade_scale (
    grade_scale_id SERIAL PRIMARY KEY,
    letter         VARCHAR(2)    NOT NULL UNIQUE,
    min_percent    NUMERIC(5, 2) NOT NULL CHECK (min_percent >= 0),
    max_percent    NUMERIC(5, 2) NOT NULL CHECK (max_percent <= 100),
    gpa_points     NUMERIC(3, 2) NOT NULL CHECK (gpa_points >= 0),
    is_passing     BOOLEAN       NOT NULL DEFAULT TRUE,
    CONSTRAINT grade_scale_range CHECK (max_percent > min_percent)
);

CREATE TABLE exams (
    exam_id        SERIAL PRIMARY KEY,
    course_id      INTEGER      NOT NULL REFERENCES courses (course_id) ON DELETE CASCADE,
    term_id        INTEGER      NOT NULL REFERENCES terms (term_id)     ON DELETE CASCADE,
    title          VARCHAR(100) NOT NULL,
    exam_type      exam_type    NOT NULL,
    exam_date      DATE         NOT NULL,
    max_score      NUMERIC(5, 2) NOT NULL DEFAULT 100 CHECK (max_score > 0),
    weight_percent NUMERIC(5, 2) NOT NULL DEFAULT 100 CHECK (weight_percent > 0 AND weight_percent <= 100)
);

CREATE TABLE exam_results (
    exam_result_id BIGSERIAL PRIMARY KEY,
    exam_id        INTEGER   NOT NULL REFERENCES exams (exam_id)       ON DELETE CASCADE,
    student_id     INTEGER   NOT NULL REFERENCES students (student_id) ON DELETE CASCADE,
    score          NUMERIC(5, 2) CHECK (score >= 0),
    is_absent      BOOLEAN   NOT NULL DEFAULT FALSE,
    graded_by      INTEGER   REFERENCES teachers (teacher_id) ON DELETE SET NULL,
    graded_at      TIMESTAMPTZ,
    remarks        VARCHAR(200),
    CONSTRAINT exam_results_unique          UNIQUE (exam_id, student_id),
    CONSTRAINT exam_results_absent_no_score CHECK (NOT is_absent OR score IS NULL)
);

-- =============================================================================
-- Domain 6: Attendance
-- =============================================================================

CREATE TABLE attendance (
    attendance_id    BIGSERIAL NOT NULL PRIMARY KEY,
    student_id       INTEGER   NOT NULL REFERENCES students (student_id)             ON DELETE CASCADE,
    class_section_id INTEGER   NOT NULL REFERENCES class_sections (class_section_id) ON DELETE CASCADE,
    attendance_date  DATE      NOT NULL,
    status           attendance_status NOT NULL DEFAULT 'present',
    recorded_by      INTEGER   REFERENCES teachers (teacher_id) ON DELETE SET NULL,
    note             VARCHAR(160),
    CONSTRAINT attendance_unique UNIQUE (student_id, attendance_date)
);

-- =============================================================================
-- Domain 7: Extracurricular activities
-- =============================================================================

CREATE TABLE activities (
    activity_id            SERIAL PRIMARY KEY,
    name                   VARCHAR(80) NOT NULL UNIQUE,
    category               activity_category NOT NULL,
    coordinator_teacher_id INTEGER     REFERENCES teachers (teacher_id) ON DELETE SET NULL,
    meeting_day            VARCHAR(9),
    meeting_time           TIME,
    location               VARCHAR(60),
    max_participants       SMALLINT    CHECK (max_participants > 0),
    annual_fee             NUMERIC(8, 2) NOT NULL DEFAULT 0 CHECK (annual_fee >= 0)
);

-- Composite PK junction.
CREATE TABLE activity_participants (
    student_id  INTEGER     NOT NULL REFERENCES students (student_id)   ON DELETE CASCADE,
    activity_id INTEGER     NOT NULL REFERENCES activities (activity_id) ON DELETE CASCADE,
    joined_on   DATE        NOT NULL DEFAULT CURRENT_DATE,
    role        VARCHAR(40) NOT NULL DEFAULT 'member',
    is_active   BOOLEAN     NOT NULL DEFAULT TRUE,
    PRIMARY KEY (student_id, activity_id)
);

-- =============================================================================
-- Domain 8: Fees and billing
-- =============================================================================

CREATE TABLE fee_types (
    fee_type_id    SERIAL PRIMARY KEY,
    code           VARCHAR(15)   NOT NULL UNIQUE,
    name           VARCHAR(80)   NOT NULL,
    default_amount NUMERIC(10, 2) NOT NULL CHECK (default_amount >= 0),
    is_recurring   BOOLEAN       NOT NULL DEFAULT TRUE,
    description    TEXT
);

CREATE TABLE invoices (
    invoice_id       SERIAL PRIMARY KEY,
    invoice_no       VARCHAR(20) NOT NULL UNIQUE,
    student_id       INTEGER     NOT NULL REFERENCES students (student_id) ON DELETE CASCADE,
    academic_year_id INTEGER     NOT NULL REFERENCES academic_years (academic_year_id),
    term_id          INTEGER     REFERENCES terms (term_id) ON DELETE SET NULL,
    issue_date       DATE        NOT NULL,
    due_date         DATE        NOT NULL,
    total_amount     NUMERIC(10, 2) NOT NULL DEFAULT 0 CHECK (total_amount >= 0),
    status           invoice_status NOT NULL DEFAULT 'draft',
    CONSTRAINT invoices_due_after_issue CHECK (due_date >= issue_date)
);

CREATE TABLE invoice_items (
    invoice_item_id BIGSERIAL PRIMARY KEY,
    invoice_id      INTEGER      NOT NULL REFERENCES invoices (invoice_id)   ON DELETE CASCADE,
    fee_type_id     INTEGER      NOT NULL REFERENCES fee_types (fee_type_id),
    description     VARCHAR(120),
    quantity        SMALLINT     NOT NULL DEFAULT 1 CHECK (quantity > 0),
    unit_amount     NUMERIC(10, 2) NOT NULL CHECK (unit_amount >= 0),
    -- Stored generated column.
    line_total      NUMERIC(12, 2) GENERATED ALWAYS AS (quantity * unit_amount) STORED
);

CREATE TABLE payments (
    payment_id   BIGSERIAL PRIMARY KEY,
    invoice_id   INTEGER     NOT NULL REFERENCES invoices (invoice_id) ON DELETE CASCADE,
    paid_on      DATE        NOT NULL,
    amount       NUMERIC(10, 2) NOT NULL CHECK (amount > 0),
    method       payment_method NOT NULL,
    reference_no VARCHAR(40) UNIQUE,
    received_by  VARCHAR(80),
    note         VARCHAR(160)
);

-- =============================================================================
-- Indexes on foreign keys and common lookup columns
-- =============================================================================

CREATE INDEX teachers_department_idx           ON teachers (department_id);
CREATE INDEX teachers_mentor_idx               ON teachers (mentor_teacher_id);
CREATE INDEX teachers_last_name_idx            ON teachers (last_name);
CREATE INDEX subjects_department_idx           ON subjects (department_id);
CREATE INDEX terms_academic_year_idx           ON terms (academic_year_id);
CREATE INDEX class_sections_year_idx           ON class_sections (academic_year_id);
CREATE INDEX class_sections_grade_idx          ON class_sections (grade_level_id);
CREATE INDEX class_sections_homeroom_idx       ON class_sections (homeroom_teacher_id);
CREATE INDEX students_section_idx              ON students (current_class_section_id);
CREATE INDEX students_last_name_idx            ON students (last_name);
CREATE INDEX students_status_idx               ON students (status);
CREATE INDEX student_guardians_guardian_idx    ON student_guardians (guardian_id);
CREATE INDEX courses_subject_idx               ON courses (subject_id);
CREATE INDEX courses_teacher_idx               ON courses (teacher_id);
CREATE INDEX enrollments_course_idx            ON enrollments (course_id);
CREATE INDEX exams_course_idx                  ON exams (course_id);
CREATE INDEX exams_term_idx                    ON exams (term_id);
CREATE INDEX exam_results_student_idx          ON exam_results (student_id);
CREATE INDEX exam_results_graded_by_idx        ON exam_results (graded_by);
CREATE INDEX attendance_section_date_idx       ON attendance (class_section_id, attendance_date);
CREATE INDEX attendance_recorded_by_idx        ON attendance (recorded_by);
CREATE INDEX activities_coordinator_idx        ON activities (coordinator_teacher_id);
CREATE INDEX activity_participants_activity_idx ON activity_participants (activity_id);
CREATE INDEX invoices_student_idx              ON invoices (student_id);
CREATE INDEX invoices_term_idx                 ON invoices (term_id);
CREATE INDEX invoices_status_idx               ON invoices (status);
CREATE INDEX invoice_items_invoice_idx         ON invoice_items (invoice_id);
CREATE INDEX invoice_items_fee_type_idx        ON invoice_items (fee_type_id);
CREATE INDEX payments_invoice_idx              ON payments (invoice_id);
