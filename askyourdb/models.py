import os

from langchain.chat_models import init_chat_model
from langchain_core.prompts import ChatPromptTemplate
from sqlalchemy import Table

from askyourdb.data_models import ResultSummary, SQLQuery, SQLSemanticValidation

# -------------------- GENERATOR MODEL -------------------- #

SQL_GEN_SYSTEM = """You are a SQL analyst. Given a database schema and a question, \
write a single valid {dialect} SELECT statement that answers it.

Rules:
- Only use tables and columns that appear in the schema below.
- Never write INSERT, UPDATE, DELETE, DROP, ALTER, or any DDL/DML statement.
- Always include a LIMIT clause (default 100 if the question doesn't imply a size), until asked otherwise.
- If the question is ambiguous, make a reasonable assumption and state it in `reasoning`.
- Use index-friendly queries and predicates wherever possible.
- If possible avoid unnecessary joins, subqueries, and row multiplication before aggregation.
- Consider corner cases when filtering, aggregating, and ordering (e.g. NULLs, cancelled/deleted records, partially paid invoices, etc.).
- Correctness is more important than optimization. If you are unsure, write a correct but possibly inefficient query.

Schema:
{schema}

Examples:
{few_shot_examples}
"""
FEW_SHOT_EXAMPLES = """\
Q: How many students are in each grade level?
A: SELECT gl.label, COUNT(*) AS student_count
   FROM students s
   JOIN class_sections cs ON cs.class_section_id = s.current_class_section_id
   JOIN grade_levels gl ON gl.grade_level_id = cs.grade_level_id
   GROUP BY gl.label, gl.level_number
   ORDER BY gl.level_number
   LIMIT 100

Q: Which teachers have no mentor assigned?
A: SELECT first_name, last_name, employee_no
   FROM teachers
   WHERE mentor_teacher_id IS NULL
   ORDER BY last_name
   LIMIT 100
"""


def render_schema(schema: dict[str, Table]) -> str:
    """Render the reflected schema as DDL-ish text for the prompt."""
    return "\n\n".join(str(table) for table in schema.values())


def build_sql_generator(schema_text: str, dialect: str):
    """Build the prompt -> model -> SQLQuery chain.

    The schema, dialect and examples are the same for every question, so they
    are bound once with .partial(). Only {question} is left to supply at call
    time.
    """
    prompt = ChatPromptTemplate.from_messages([
        ("system", SQL_GEN_SYSTEM),
        ("human", "{question}"),
    ]).partial(
        dialect=dialect,
        schema=schema_text,
        few_shot_examples=FEW_SHOT_EXAMPLES,
    )
    model = init_chat_model("google_genai:gemini-3.5-flash-lite", temperature=0)
    return prompt | model.with_structured_output(SQLQuery)


# -------------------- SEMANTIC VALIDATION MODEL -------------------- #

SEMANTIC_VALIDATION_SYSTEM = """\
You are a strict SQL quality reviewer.

Your task is to decide whether the generated SQL correctly answers the user's
question using the provided database schema.

Review these categories:

1. Intent
- Does the query answer exactly what the user asked?
- Does it return the requested entities and measures?
- Are assumptions reasonable and reflected in the query?

2. Schema and relationships
- Are joins based on the correct primary-key and foreign-key relationships?
- Could any join duplicate rows or inflate aggregates?
- Are table aliases used consistently?
- Are the selected columns appropriate?

3. Filters and edge cases
- Are NULL values handled correctly?
- Are cancelled, deleted, inactive, or irrelevant records excluded when required?
- Are partially paid, unpaid, zero-value, or overpaid records handled correctly?
- Could status filters disagree with calculated values?
- Are date boundaries and inclusive/exclusive comparisons correct?

4. Aggregation and ranking
- Are GROUP BY expressions correct?
- Are aggregates calculated at the correct grain?
- Should a condition use WHERE or HAVING?
- Is the ordering applied to the intended calculated value?
- Does LIMIT apply after filtering and ordering?

5. Performance risks
Flag likely risks such as:
- unnecessary joins or subqueries
- row multiplication before aggregation
- filtering too late
- functions applied to filtered columns
- missing selective predicates
- repeated correlated subqueries
- sorting or grouping very large intermediate results
- use of DISTINCT to hide join mistakes
- use index friendly queries and predicates

Be critical about the correctness of the query.
Do not reject a query merely because it could theoretically be optimized.
Reject it only when the performance risk is substantial or likely to cause
incorrect behavior at the expected scale.

Do not perform syntax or security validation. Those are handled separately.

Return is_valid=false when the query is incorrect, ambiguous in a harmful way,
has a serious edge-case problem, or has a substantial performance risk.
Return concise, actionable feedback explaining exactly what should change.
"""


def build_sql_semantic_validator():
    prompt = ChatPromptTemplate.from_messages([
        ("system", SEMANTIC_VALIDATION_SYSTEM),
        (
            "human",
            "Question:\n{question}\n\n"
            "Database schema:\n{schema}\n\n"
            "SQL dialect:\n{dialect}\n\n"
            "Generated SQL:\n{sql}\n\n"
            "Generator reasoning:\n{reasoning}",
        ),
    ])

    model_name = os.environ.get(
        "SEMANTIC_MODEL",
        "google_genai:gemini-3.5-flash-lite",
    )
    model = init_chat_model(model_name, temperature=0)

    return prompt | model.with_structured_output(SQLSemanticValidation)


# -------------------- RESULT SUMMARIZER MODEL -------------------- #

RESULT_SUMMARY_SYSTEM = """\
You are a data analyst summarizing the result of a validated, read-only SQL query.

Answer the user's question using only the returned rows. Do not invent values,
rows, trends, or explanations that are not supported by the data.

Return:
- answer: a concise natural-language answer
- row_count: the exact number of returned rows
- sql_used: the exact SQL query provided
- caveats: limitations, assumptions, empty-result notes, or data-quality concerns
"""


def build_result_summarizer():
    prompt = ChatPromptTemplate.from_messages([
        ("system", RESULT_SUMMARY_SYSTEM),
        (
            "human",
            "Question:\n{question}\n\n"
            "SQL used:\n{sql}\n\n"
            "Rows returned:\n{rows}",
        ),
    ])
    model_name = os.environ.get(
        "SUMMARY_MODEL",
        "google_genai:gemini-3.5-flash-lite",
    )
    model = init_chat_model(model_name, temperature=0)
    return prompt | model.with_structured_output(ResultSummary)
