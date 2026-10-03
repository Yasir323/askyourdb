# School database

A Dockerised PostgreSQL 17 instance with a school-management schema and deterministic
dummy data. It exists as a realistic introspection target for the schema summarizer in
`examples/school_demo.py`.

See [SCHEMA.md](SCHEMA.md) for the entity relationship diagram.

## Running it

```bash
docker compose up -d
```

The init scripts in `db/init/` run in filename order, **once**, the first time the data
volume is created:

| Script | Contents |
| --- | --- |
| `01_schema.sql` | 10 enum types, 22 tables, constraints, 30 indexes |
| `02_seed.sql` | All dummy data |
| `03_views.sql` | `v_student_report_card`, `v_outstanding_fees` |

Connect with:

```
postgresql://school:school@localhost:5432/school_db
```

or from a shell:

```bash
docker exec -it school_db psql -U school -d school_db
```

If port 5432 is already in use locally, change the host side of the port mapping in
`docker-compose.yml` (e.g. `"5433:5432"`).

## Reloading after a schema change

Editing the SQL is not enough — the init scripts only run against an empty volume. Drop
the volume and start over:

```bash
docker compose down -v && docker compose up -d
```

## Using it from `examples/school_demo.py`

`examples/school_demo.py` loads `.env` and reads the `ASKYOURDB_*` variables. `.env.example` already
points `ASKYOURDB_DSN` at this container; add your model key:

```bash
cp .env.example .env   # set ASKYOURDB_API_KEY
uv sync --extra google
uv run python examples/school_demo.py
```

## Seeded volumes

| Table | Rows | Table | Rows |
| --- | ---: | --- | ---: |
| `departments` | 8 | `exams` | 1,524 |
| `teachers` | 40 | `exam_results` | 27,192 |
| `subjects` | 18 | `attendance` | 35,000 |
| `academic_years` | 2 | `activities` | 12 |
| `terms` | 6 | `activity_participants` | 557 |
| `grade_levels` | 12 | `fee_types` | 8 |
| `class_sections` | 56 | `invoices` | 1,452 |
| `students` | 500 | `invoice_items` | 6,934 |
| `guardians` | 666 | `payments` | 1,236 |
| `student_guardians` | 666 | `grade_scale` | 11 |
| `courses` | 254 | `enrollments` | 4,532 |

## Shape of the data

- Two academic years, `2024-2025` and `2025-2026`. Only the later one is flagged
  `is_current` and only it carries courses, exams, attendance and invoices — the earlier
  year exists so that year-scoped queries have something to exclude.
- Class sections A and B exist for every grade, plus a C section for grades 9-12.
- Attendance covers the weekdays of the current year's **first term only** (~70 school
  days), which keeps the table at a workable 35k rows.
- Each course runs one 20-mark quiz (30% weight) and one 100-mark paper (70%) per term.
  Roughly 2% of results are marked absent, and absent rows carry a `NULL` score.
- Fees: every active student gets one invoice per term. About 70% are paid in full, 15%
  partially, and 15% not at all, so `v_outstanding_fees` returns ~190 students.
- All values are produced by modular arithmetic over `generate_series` rather than
  `random()`, so a rebuild reproduces the data exactly.

## Deliberate schema features

These exist to give the introspector something more interesting than a star of plain
foreign keys:

- **Self-referencing FK** — `teachers.mentor_teacher_id`
- **Circular FK pair** — `teachers.department_id` ↔ `departments.head_teacher_id`, with
  the second constraint `DEFERRABLE INITIALLY DEFERRED`
- **Composite primary keys** — `enrollments`, `student_guardians`,
  `activity_participants`
- **Generated column** — `invoice_items.line_total`
- **Partial unique index** — `academic_years (is_current) WHERE is_current`
- **A table with no incoming or outgoing FKs** — `grade_scale`, joined on a value range
  instead
- **A department with no subjects** — `Student Affairs`, so empty relations are covered

## Known limitation

`exam_results.score` is checked for `>= 0` but not against `exams.max_score`, because a
`CHECK` constraint cannot reference another table. The seed data respects the bound (max
generated score is 96% of `max_score`); enforcing it properly would need a trigger.
