from sqlalchemy import Integer, Text

from askyourdb.data_models import (
    CheckConstraint,
    Column,
    PrimaryKey,
    Relation,
    Table,
    UniqueConstraint,
)


def test_schema_models_render_constraints_and_table():
    table = Table(
        name="students",
        columns=[Column("student_id", Integer(), "INTEGER", False)],
        primary_key=PrimaryKey(("student_id",), "students_pkey"),
        relations=[
            Relation(
                ("class_section_id",),
                "class_sections",
                ("class_section_id",),
                "students_section_fkey",
                "CASCADE",
                "NO ACTION",
            )
        ],
        constraints=[
            UniqueConstraint(("email",), "students_email_key"),
            CheckConstraint("student_id > 0", "students_id_check"),
        ],
    )

    rendered = str(table)

    assert "students (" in rendered
    assert "student_id INTEGER NOT NULL" in rendered
    assert "CONSTRAINT students_pkey PRIMARY KEY (student_id)" in rendered
    assert "ON DELETE CASCADE ON UPDATE NO ACTION" in rendered
    assert "CONSTRAINT students_email_key UNIQUE (email)" in rendered
    assert "CONSTRAINT students_id_check CHECK (student_id > 0)" in rendered


def test_schema_models_omit_optional_constraint_names_and_defaults():
    column = Column("name", Text(), "TEXT", True, "DEFAULT 'unknown'")
    table = Table(
        name="example",
        columns=[column],
        primary_key=PrimaryKey(("name",)),
        constraints=[UniqueConstraint(("name",)), CheckConstraint("name <> ''")],
    )

    rendered = str(table)

    assert "name TEXT DEFAULT 'unknown'" in rendered
    assert "PRIMARY KEY (name)" in rendered
    assert "UNIQUE (name)" in rendered
    assert "CHECK (name <> '')" in rendered
