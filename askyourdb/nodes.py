from askyourdb.states import AnalystState
from askyourdb.sql_validator import SqlValidator


def generate_sql_node(state: AnalystState, model) -> AnalystState:
    prompt_question = state.get("question", None)
    if state.get("error_feedback"):
        prompt_question += (
            "\n\nThe previous SQL attempt failed validation. "
            "Fix it using this feedback:\n"
            f"{state['error_feedback']}"
        )
    result = model.invoke({
        "question": prompt_question
    })
    return {
        **state,
        "sql_query": result,
        "error_feedback": None,
        "attempts": state.get("attempts", 0) + 1,
    }


def validate_sql_node(state: AnalystState, validator: SqlValidator) -> AnalystState:
    result = validator.validate(
        state["sql_query"].sql
    )
    if result["is_valid"]:
        # normalize state: store the possibly-rewritten (LIMIT-injected) SQL
        updated_query = state["sql_query"].model_copy(
            update={"sql": result["sql_query"]}
        )
        return {
            **state,
            "sql_query": updated_query,
            "error_feedback": None
        }
    else:
        return {
            **state,
            "error_feedback": "; ".join(result["error_message"])
        }


def route_after_static_validation(state: AnalystState) -> str:
    if state.get("error_feedback"):
        if state["attempts"] >= state["max_attempts"]:
            return "failure"
        return "retry"

    return "semantic"


def semantic_validate_sql_node(state: AnalystState, validator) -> dict:
    query = state["sql_query"]

    result = validator.invoke({
        "question": state["question"],
        "schema": state["schema"],
        "dialect": state["dialect"],
        "sql": query.sql,
        "reasoning": query.reasoning,
    })

    if result.is_valid:
        return {"error_feedback": None}

    return {
        "error_feedback": (
            "Semantic validation failed: "
            f"{result.feedback}"
        )
    }


def route_after_semantic_validation(state: AnalystState) -> str:
    if state.get("error_feedback") is None:
        return "success"

    if state["attempts"] >= state["max_attempts"]:
        return "failure"

    return "retry"


def execute_sql_node(state: AnalystState, executor) -> AnalystState:
    try:
        rows = executor.execute_query(state["sql_query"])
        return {
            **state,
            "rows": rows,
            "execution_error": None,
            "error_feedback": None
        }
    except Exception as e:
        message = f"SQL execution failed: {_database_message(e)}"
        return {
            **state,
            "rows": None,
            "execution_error": message,
            "error_feedback": message
        }


def _database_message(error: Exception) -> str:
    """The driver's own message, first line only.

    SQLAlchemy wraps it with the full SQL and a docs link, and the driver adds
    a caret diagram; neither helps the user or the model's retry.
    """
    text = str(getattr(error, "orig", None) or error).strip()
    return text.splitlines()[0] if text else type(error).__name__


def route_after_execution(state: AnalystState) -> str:
    if state.get("execution_error") is None:
        return "success"

    if state["attempts"] >= state["max_attempts"]:
        return "failure"

    return "retry"


def summarize_results_node(state: AnalystState, summarizer) -> dict:
    summary_attempts = state.get("summary_attempts", 0) + 1
    try:
        summary = summarizer.invoke({
            "question": state["question"],
            "sql": state["sql_query"].sql,
            "rows": state["rows"],
        })

        return {
            "summary": summary,
            "summary_error": None,
            "summary_attempts": summary_attempts,
        }
    except Exception as error:
        return {
            "summary": None,
            "summary_error": str(error),
            "summary_attempts": summary_attempts,
        }


def route_after_summary(state: AnalystState) -> str:
    if state["summary_error"] is None:
        return "success"

    if state["summary_attempts"] >= state["max_summary_attempts"]:
        return "failure"

    return "retry_summary"
