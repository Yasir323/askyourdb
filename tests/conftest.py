import pytest
from sqlalchemy import Integer, Numeric, Text

from askyourdb.data_models import Column, Table
from askyourdb.sql_validator import SqlValidator


@pytest.fixture
def schema():
    return {
        "students": Table(
            name="students",
            columns=[
                Column("student_id", Integer(), "INTEGER", False),
                Column("first_name", Text(), "TEXT", False),
                Column("last_name", Text(), "TEXT", False),
            ],
        ),
        "invoices": Table(
            name="invoices",
            columns=[
                Column("invoice_id", Integer(), "INTEGER", False),
                Column("student_id", Integer(), "INTEGER", False),
                Column("total_amount", Numeric(), "NUMERIC", False),
                Column("status", Text(), "TEXT", False),
            ],
        ),
        "payments": Table(
            name="payments",
            columns=[
                Column("invoice_id", Integer(), "INTEGER", False),
                Column("amount", Numeric(), "NUMERIC", False),
            ],
        ),
    }


@pytest.fixture
def validator(schema):
    return SqlValidator(schema=schema, dialect="PostgreSQL")
