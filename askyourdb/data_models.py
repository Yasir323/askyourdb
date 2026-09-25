from dataclasses import field
from typing import NotRequired, TypedDict

from pydantic import BaseModel, Field
from pydantic.dataclasses import dataclass
from sqlalchemy.types import TypeEngine


class SQLQuery(BaseModel):
    sql: str = Field(description="A single valid SELECT statement, no trailing semicolon required")
    reasoning: str = Field(description="Brief explanation of how the query answers the question")
    tables_used: list[str] = Field(description="Names of tables referenced in the query")


class SQLValidatorResult(TypedDict):
    is_valid: bool
    error_message: list[str] = field(default_factory=list)
    sql_query: SQLQuery | None
    #: The LIMIT askyourdb injected or capped to; None when the query's own
    #: limit (or a single-row aggregate) was kept. Only set on success.
    row_limit: NotRequired[int | None]


class SQLSemanticValidation(BaseModel):
    is_valid: bool
    feedback: str = ""


class ResultSummary(BaseModel):
    answer: str
    row_count: int
    sql_used: str
    caveats: list[str] = Field(default_factory=list)


def _with_name(name: str, body: str) -> str:
    """Prefix a constraint body with its name, when the database gave it one."""
    return f"CONSTRAINT {name} {body}" if name else body


@dataclass(frozen=True, config={"arbitrary_types_allowed": True})
class Column:
    name: str
    type: TypeEngine
    #: ``type`` compiled for the source dialect. Keeps enum type names, which
    #: ``str(TypeEngine)`` flattens to a generic VARCHAR.
    type_sql: str
    nullable: bool
    default: str = ""
    #: Allowed values of an enum column. The compiled type is only the enum's
    #: name, so without these the model has to guess the labels.
    enum_values: tuple[str, ...] = ()

    def __str__(self) -> str:
        parts = [self.name, self.type_sql]
        if not self.nullable:
            parts.append("NOT NULL")
        if self.default:
            parts.append(self.default)
        if self.enum_values:
            parts.append("/* one of: " + ", ".join(f"'{v}'" for v in self.enum_values) + " */")
        return " ".join(parts)


@dataclass(frozen=True)
class PrimaryKey:
    columns: tuple[str, ...]
    name: str = ""

    def __str__(self) -> str:
        return _with_name(self.name, f"PRIMARY KEY ({', '.join(self.columns)})")


@dataclass(frozen=True)
class Relation:
    columns: tuple[str, ...]
    referred_table: str
    referred_columns: tuple[str, ...]
    name: str = ""
    on_delete: str = ""
    on_update: str = ""

    def __str__(self) -> str:
        body = (
            f"FOREIGN KEY ({', '.join(self.columns)}) "
            f"REFERENCES {self.referred_table} ({', '.join(self.referred_columns)})"
        )
        if self.on_delete:
            body += f" ON DELETE {self.on_delete}"
        if self.on_update:
            body += f" ON UPDATE {self.on_update}"
        return _with_name(self.name, body)


@dataclass(frozen=True)
class UniqueConstraint:
    columns: tuple[str, ...]
    name: str = ""

    def __str__(self) -> str:
        return _with_name(self.name, f"UNIQUE ({', '.join(self.columns)})")


@dataclass(frozen=True)
class CheckConstraint:
    text: str
    name: str = ""

    def __str__(self) -> str:
        return _with_name(self.name, f"CHECK ({self.text})")


@dataclass
class Table:
    name: str
    columns: list[Column] = field(default_factory=list)
    primary_key: PrimaryKey | None = None
    relations: list[Relation] = field(default_factory=list)
    constraints: list[UniqueConstraint | CheckConstraint] = field(default_factory=list)

    def __str__(self) -> str:
        lines = [f"{self.name} ("]
        lines += [f"    {column}," for column in self.columns]
        if self.primary_key:
            lines.append(f"    {self.primary_key},")
        lines += [f"    {relation}," for relation in self.relations]
        lines += [f"    {constraint}," for constraint in self.constraints]
        if len(lines) > 1:
            lines[-1] = lines[-1].rstrip(",")
        lines.append(")")
        return "\n".join(lines)
