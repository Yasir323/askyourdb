# School database — design

**Date:** 2026-08-30
**Status:** implemented

## Purpose

`main.py` contains a `SchemaIntrospector` that reflects a database with SQLAlchemy and
will eventually summarize it. It had no database to point at. This provides one: a
Dockerised PostgreSQL instance with a school-management schema and dummy data.

The database is a **test target for the summarizer**, not an application backend. That
decides the trade-offs: schema richness matters more than data volume, and the schema
should exercise reflection features (self-references, cycles, composite keys, enums,
generated columns) rather than just being correct.

Difficulty level chosen: *realistic and clean*. Production-shaped modelling with
deliberate variety, but no adversarial mess — no inconsistent naming, no PK-less tables,
no multiple schemas. Those would make it hard to tell a summarizer bug from a schema wart.

## Decisions

| Decision | Choice | Reason |
| --- | --- | --- |
| Container setup | `docker-compose.yml` + `db/init/*.sql` on the official `postgres:17-alpine` image | Edit SQL, `down -v && up`, done. A custom Dockerfile would need a rebuild per change. |
| Data generation | Pure SQL: handwritten reference rows, `generate_series` for bulk | No extra dependency, no second step after `up`, and reproducible. |
| Determinism | Modular arithmetic, not `random()` | A rebuild produces byte-identical data, so summarizer output is comparable across runs. |
| Volume | ~500 students | Enough for the aggregate views to be meaningful; small enough to seed in seconds. |

## Layout

```
docker-compose.yml
db/init/01_schema.sql   enums, tables, constraints, indexes
db/init/02_seed.sql     all dummy data
db/init/03_views.sql    two reporting views
db/SCHEMA.md            mermaid ER diagram
db/README.md            how to run, reset, and what's inside
```

## Schema

22 tables in eight domains:

| Domain | Tables |
| --- | --- |
| Organisation | `departments`, `teachers`, `subjects` |
| Academic structure | `academic_years`, `terms`, `grade_levels`, `class_sections` |
| People | `students`, `guardians`, `student_guardians` |
| Courses | `courses`, `enrollments` |
| Assessment | `grade_scale`, `exams`, `exam_results` |
| Attendance | `attendance` |
| Extracurricular | `activities`, `activity_participants` |
| Fees | `fee_types`, `invoices`, `invoice_items`, `payments` |

Fees is modelled as the full invoice / line-item / payment trio rather than a single
`fee_payments` table. This pushes the count above the 15-18 originally sketched, but a
flattened version cannot express partial payment, which is what makes
`v_outstanding_fees` worth having.

`courses` is the join point of the whole academic side: one subject, taught to one class
section, by one teacher. Exams hang off courses; enrolments connect students to courses.

### Features included for the introspector

- Self-referencing FK: `teachers.mentor_teacher_id`
- Circular FK pair: `teachers.department_id` ↔ `departments.head_teacher_id`, closed with
  a `DEFERRABLE INITIALLY DEFERRED` constraint added after both tables exist
- Composite PKs on all three junction tables
- 10 native enum types
- Stored generated column: `invoice_items.line_total`
- Partial unique index: only one `academic_years` row may be `is_current`
- `grade_scale`: no foreign keys at all, joined on a percentage range
- `Student Affairs`: a department with no subjects, so empty relations are represented

## Seed data shape

Two academic years; only `2025-2026` is current and only it carries courses, exams,
attendance and invoices. Sections A and B for every grade plus C for grades 9-12 (28 per
year). Grade-appropriate subject lists give 254 courses; every student takes every course
offered to their section.

Each course runs one quiz (20 marks, 30% weight) and one paper (100 marks, 70%) per term.
~2% of results are absences with a `NULL` score. Attendance covers weekdays of the first
term only, to keep the table near 35k rows rather than 100k.

Every active student is invoiced per term. 70% of invoices are paid in full, 15%
partially, 15% not at all.

## Views

- `v_student_report_card` — student × course weighted average, matched to `grade_scale`
  on percentage range, with letter grade and GPA points.
- `v_outstanding_fees` — student × academic year, invoiced minus paid, filtered to
  non-zero balances.

## Verification performed

- `docker compose up -d` from a clean volume: container reaches `healthy`, init logs
  contain no SQL errors.
- Row counts confirmed per table against expected volumes.
- Integrity checks: all 8 departments have a head; 22 teachers have a mentor; no course
  lacks a teacher; **no `exam_results.score` exceeds its exam's `max_score`**; all 4,532
  enrolments have a computed `final_score`.
- Both views return rows; every report-card row matches a `grade_scale` band (0
  unmatched).
- `uv run python main.py` reflects all 22 tables with correct enum types, the
  self-referencing FK, and both sides of the circular FK pair.

## Known limitation

`exam_results.score` cannot be `CHECK`-constrained against `exams.max_score` because a
check constraint cannot reference another table. The seed data respects the bound;
enforcing it would require a trigger, which was judged not worth it for a test fixture.

## Out of scope

The summarizer itself. `main.py` was changed only to read a DSN from `SCHOOL_DB_DSN` with
the local container as the default, and `pyproject.toml` gained `psycopg[binary]` so
SQLAlchemy can actually connect.
