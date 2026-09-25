from langchain.chat_models import init_chat_model
from langchain_core.prompts import ChatPromptTemplate
from pydantic import ValidationError
from sqlalchemy import Table

from askyourdb.config import ConfigError, LLMConfig
from askyourdb.data_models import ResultSummary, SQLQuery, SQLSemanticValidation

# init_chat_model provider name -> askyourdb pip extra that installs it.
PROVIDER_EXTRAS = {
    "anthropic": "anthropic",
    "openai": "openai",
    "google_genai": "google",
    "groq": "groq",
    "ollama": "ollama",
}


def build_llm(config: LLMConfig):
    """Create the chat model for one pipeline stage from the user's config.

    The key is only passed when configured; otherwise the provider SDK reads its
    standard environment variable (ANTHROPIC_API_KEY, OPENAI_API_KEY, ...).
    """
    kwargs = {"temperature": config.temperature}
    if config.api_key is not None:
        kwargs["api_key"] = config.api_key.get_secret_value()
    try:
        return init_chat_model(config.model, **kwargs)
    except ImportError as error:
        extra = PROVIDER_EXTRAS.get(config.provider)
        hint = (
            f'pip install "askyourdb[{extra}]"' if extra
            else f"install the LangChain integration package for '{config.provider}'"
        )
        raise ConfigError(
            f"The '{config.provider}' model provider is not installed. "
            f"Run: {hint}\n({error})"
        ) from None
    except Exception as error:
        # Provider SDKs raise their own errors here (missing credentials, bad
        # arguments). Keep one line, and never echo the key back.
        raise ConfigError(
            f"Could not initialize model '{config.model}': "
            f"{_describe_init_error(error, config)}"
        ) from None


def _describe_init_error(error: Exception, config: LLMConfig) -> str:
    if isinstance(error, ValidationError):
        # str(ValidationError) includes the raw input, which holds the api_key.
        text = "; ".join(
            f"{'.'.join(str(part) for part in item['loc'])}: {item['msg']}"
            for item in error.errors()
        )
    else:
        text = str(error).strip().splitlines()[0] if str(error).strip() else ""
    text = text or type(error).__name__
    if config.api_key is not None and config.api_key.get_secret_value():
        text = text.replace(config.api_key.get_secret_value(), "**********")
    return text


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
"""


def render_schema(schema: dict[str, Table]) -> str:
    """Render the reflected schema as DDL-ish text for the prompt."""
    return "\n\n".join(str(table) for table in schema.values())


def build_sql_generator(schema_text: str, dialect: str, llm_config: LLMConfig):
    """Build the prompt -> model -> SQLQuery chain.

    The schema and dialect are the same for every question, so they are bound
    once with .partial(). Only {question} is left to supply at call time.
    """
    prompt = ChatPromptTemplate.from_messages([
        ("system", SQL_GEN_SYSTEM),
        ("human", "{question}"),
    ]).partial(
        dialect=dialect,
        schema=schema_text,
    )
    return prompt | build_llm(llm_config).with_structured_output(SQLQuery)


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


def build_sql_semantic_validator(llm_config: LLMConfig):
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

    model = build_llm(llm_config)

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


def build_result_summarizer(llm_config: LLMConfig):
    prompt = ChatPromptTemplate.from_messages([
        ("system", RESULT_SUMMARY_SYSTEM),
        (
            "human",
            "Question:\n{question}\n\n"
            "SQL used:\n{sql}\n\n"
            "Rows returned:\n{rows}",
        ),
    ])
    model = build_llm(llm_config)
    return prompt | model.with_structured_output(ResultSummary)
