from sqlalchemy import create_engine, MetaData, inspect
from sqlalchemy import CheckConstraint as SACheckConstraint
from sqlalchemy import ForeignKeyConstraint as SAForeignKeyConstraint
from sqlalchemy import PrimaryKeyConstraint as SAPrimaryKeyConstraint
from sqlalchemy import UniqueConstraint as SAUniqueConstraint

from askyourdb.data_models import CheckConstraint, Column, PrimaryKey, Relation, Table, UniqueConstraint


class SchemaIntrospector:
    def __init__(self, dsn: str):
        self.dsn = dsn
        self._schema: dict[str, Table] = {}
        self._engine = None

    @property
    def engine(self):
        return self._engine

    def load_db(self):
        self._engine = create_engine(self.dsn)
        metadata = MetaData()
        metadata.reflect(bind=self._engine)
        inspector = inspect(self._engine)
        for table_name in metadata.tables:
            table = Table(name=table_name)
            self._schema[table_name] = table
            table_obj = metadata.tables[table_name]

            # Columns
            for column in table_obj.columns:
                table.columns.append(Column(
                    name=column.name,
                    type=column.type,
                    type_sql=column.type.compile(self._engine.dialect),
                    nullable=column.nullable,
                    default=self._server_default(column),
                ))

            # Primary key
            pk_constraint = inspector.get_pk_constraint(table_name)
            if pk_constraint and pk_constraint.get("constrained_columns"):
                table.primary_key = PrimaryKey(
                    columns=tuple(pk_constraint["constrained_columns"]),
                    name=pk_constraint.get("name") or "",
                )

            # Relations
            for fk in inspector.get_foreign_keys(table_name):
                options = fk.get("options", {})
                table.relations.append(Relation(
                    columns=tuple(fk["constrained_columns"]),
                    referred_table=fk["referred_table"],
                    referred_columns=tuple(fk["referred_columns"]),
                    name=fk.get("name") or "",
                    on_delete=options.get("ondelete") or "",
                    on_update=options.get("onupdate") or "",
                ))

            # Other constraints. table_obj.constraints is a set, so sort for a
            # stable rendering across runs.
            other_constraints = sorted(
                (c for c in table_obj.constraints
                if not isinstance(c, (SAForeignKeyConstraint, SAPrimaryKeyConstraint))),
                key=lambda c: (type(c).__name__, c.name or ""),
            )

            for constraint in other_constraints:
                if isinstance(constraint, SAUniqueConstraint):
                    table.constraints.append(UniqueConstraint(
                        columns=tuple(col.name for col in constraint.columns),
                        name=constraint.name or "",
                    ))

                elif isinstance(constraint, SACheckConstraint):
                    table.constraints.append(CheckConstraint(
                        text=f"{constraint.sqltext}",
                        name=constraint.name or "",
                    ))

    @staticmethod
    def _server_default(column) -> str:
        if not column.server_default:
            return ""
        # Check if it is a database-calculated computed column
        if hasattr(column.server_default, "sqltext"):
            return f"GENERATED ALWAYS AS ({column.server_default.sqltext})"
        if hasattr(column.server_default, "arg"):
            return f"DEFAULT {column.server_default.arg}"
        return f"DEFAULT {column.server_default}"

    def get_schema(self) -> dict[str, Table]:
        return self._schema

    def close(self):
        if self._engine:
            self._engine.dispose()
            self._engine = None
