-- =============================================================================
-- 03_views.sql — reporting views
-- =============================================================================

SET client_min_messages = warning;

-- -----------------------------------------------------------------------------
-- One row per student per course: weighted average, letter grade and GPA.
-- -----------------------------------------------------------------------------

CREATE VIEW v_student_report_card AS
WITH course_average AS (
    SELECT er.student_id,
           e.course_id,
           ROUND(
               SUM(er.score / e.max_score * 100 * e.weight_percent) / SUM(e.weight_percent),
           2) AS average_percent,
           COUNT(*)                                     AS exams_taken,
           COUNT(*) FILTER (WHERE er.is_absent)         AS exams_missed
      FROM exam_results AS er
      JOIN exams        AS e ON e.exam_id = er.exam_id
     WHERE er.score IS NOT NULL
     GROUP BY er.student_id, e.course_id
)
SELECT s.student_id,
       s.admission_no,
       s.first_name || ' ' || s.last_name AS student_name,
       ay.name                            AS academic_year,
       gl.label                           AS grade_level,
       cs.section_label,
       sub.code                           AS subject_code,
       sub.name                           AS subject_name,
       t.first_name || ' ' || t.last_name AS teacher_name,
       ca.average_percent,
       gs.letter                          AS grade_letter,
       gs.gpa_points,
       gs.is_passing,
       ca.exams_taken
  FROM course_average  AS ca
  JOIN students        AS s   ON s.student_id        = ca.student_id
  JOIN courses         AS c   ON c.course_id         = ca.course_id
  JOIN subjects        AS sub ON sub.subject_id      = c.subject_id
  JOIN class_sections  AS cs  ON cs.class_section_id = c.class_section_id
  JOIN grade_levels    AS gl  ON gl.grade_level_id   = cs.grade_level_id
  JOIN academic_years  AS ay  ON ay.academic_year_id = cs.academic_year_id
  LEFT JOIN teachers   AS t   ON t.teacher_id        = c.teacher_id
  LEFT JOIN grade_scale AS gs ON ca.average_percent BETWEEN gs.min_percent AND gs.max_percent;

COMMENT ON VIEW v_student_report_card IS
    'Per-student, per-course weighted average with the matching letter grade.';

-- -----------------------------------------------------------------------------
-- Students carrying an unpaid balance, by academic year.
-- -----------------------------------------------------------------------------

CREATE VIEW v_outstanding_fees AS
SELECT s.student_id,
       s.admission_no,
       s.first_name || ' ' || s.last_name AS student_name,
       ay.name                            AS academic_year,
       COUNT(*)                                                     AS invoice_count,
       COUNT(*) FILTER (WHERE i.status = 'overdue')                 AS overdue_invoices,
       SUM(i.total_amount)                                          AS total_invoiced,
       COALESCE(SUM(paid.amount_paid), 0)                           AS total_paid,
       SUM(i.total_amount) - COALESCE(SUM(paid.amount_paid), 0)     AS balance_due,
       MIN(i.due_date) FILTER (WHERE i.status <> 'paid')            AS earliest_unpaid_due_date
  FROM invoices       AS i
  JOIN students       AS s  ON s.student_id        = i.student_id
  JOIN academic_years AS ay ON ay.academic_year_id = i.academic_year_id
  LEFT JOIN LATERAL (
        SELECT SUM(p.amount) AS amount_paid
          FROM payments AS p
         WHERE p.invoice_id = i.invoice_id
       ) AS paid ON TRUE
 GROUP BY s.student_id, s.admission_no, s.first_name, s.last_name, ay.name
HAVING SUM(i.total_amount) - COALESCE(SUM(paid.amount_paid), 0) > 0;

COMMENT ON VIEW v_outstanding_fees IS
    'Students with a non-zero fee balance, aggregated per academic year.';
