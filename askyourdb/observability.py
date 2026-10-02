import os


def configure_langsmith() -> bool:
    """Configure optional LangSmith tracing from environment variables."""
    enabled = os.environ.get("LANGCHAIN_TRACING_V2", "false").lower() in {
        "1",
        "true",
        "yes",
    }
    if enabled and os.environ.get("LANGCHAIN_API_KEY"):
        os.environ.setdefault("LANGCHAIN_PROJECT", "askyourdb")
        return True
    return False
