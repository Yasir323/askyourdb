from sqlalchemy import Table
import sqlglot
from sqlglot import exp

from askyourdb.data_models import SQLValidatorResult

DEFAULT_ROW_LIMIT = 100
MAX_ROW_LIMIT = 1000


class SqlValidator:
    def __init__(self, schema: dict[str, Table], dialect: str):
        self.schema = schema
        self.dialect = {
            "postgresql": "postgres",
        }.get(dialect.lower(), dialect)
        self._tables = {
            name.lower(): {
                c.name.lower() for c in table.columns
            }
            for name, table in schema.items()
        }

    def validate(self, sql_query: str) -> SQLValidatorResult:
        errors = []
        try:
            parsed = sqlglot.parse_one(sql_query, read=self.dialect)
        except sqlglot.errors.ParseError as e:
            errors.append(f"Parse error: {str(e)}")
            return SQLValidatorResult(
                is_valid=False,
                error_message=errors,
                sql_query=None
            )

        # 1. Must be a single SELECT statement (blocks INSERT/UPDATE/DELETE/DDL,
        #    and blocks a semicolon-separated second statement smuggled in).
        if not isinstance(parsed, (exp.Select, exp.With, exp.Union)):
            errors.append(f"Only Read statements are allowed. Found: {type(parsed).__name__}")

        # 2. No mutating expressions anywhere in the tree, including inside CTEs/subqueries.
        forbidden = (
            exp.Insert,
            exp.Update,
            exp.Delete,
            exp.Drop,
            exp.Create,
            exp.TruncateTable,
            exp.Grant,
            exp.Alter
        )
        for node in parsed.walk():
            if isinstance(node, forbidden):
                errors.append(f"Mutating statements are not allowed. Found: {type(node).__name__}")

        # 3. All referenced tables and columns must exist in the schema to prevent Halucination.
        cte_names = {
            cte.alias_or_name.lower() for cte in parsed.find_all(exp.CTE)
        }
        referenced_tables = {
            table.name.lower() for table in parsed.find_all(exp.Table)
        }
        unknown_tables = referenced_tables - self._tables.keys() - cte_names
        if unknown_tables:
            errors.append(f"Unknown tables referenced: {', '.join(unknown_tables)}")

        # 4. Every column referenced (that's qualified with a known table) must exist on it.
        #    Unqualified columns are skipped here — resolving them needs join-aware
        #    alias tracking, which is a reasonable v2 improvement, not a v1 blocker.
        table_aliases = {
            table.alias_or_name.lower(): table.name.lower()
            for table in parsed.find_all(exp.Table)
            if table.name.lower() in self._tables
        }
        for col in parsed.find_all(exp.Column):
            table_alias = col.table.lower() if col.table else None
            table_name = table_aliases.get(table_alias) if table_alias else None
            if table_name and col.name.lower() not in self._tables[table_name]:
                errors.append(f"Unknown column '{col.name}' on table '{table_alias}'")

        if errors:
            return SQLValidatorResult(
                is_valid=False,
                error_message=errors,
                sql_query=None
            )

        # 5. Enforce a LIMIT — inject one if missing, cap it if excessive.
        sql = self._enforce_limit(parsed)

        return SQLValidatorResult(
            is_valid=True,
            error_message=[],
            sql_query=sql
        )

    def _enforce_limit(self, parsed: exp.Expression) -> str:
        existing = parsed.args.get("limit")
        if existing is None:
            parsed.set("limit", exp.Limit(expression=exp.Literal.number(DEFAULT_ROW_LIMIT)))
        else:
            n = int(existing.expression.this)
            if n > MAX_ROW_LIMIT:
                existing.set("expression", exp.Literal.number(MAX_ROW_LIMIT))
        return parsed.sql(dialect=self.dialect)
