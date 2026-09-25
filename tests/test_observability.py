from askyourdb.observability import configure_langsmith


def test_langsmith_tracing_requires_enabled_flag_and_api_key(monkeypatch):
    monkeypatch.delenv("LANGCHAIN_TRACING_V2", raising=False)
    monkeypatch.delenv("LANGCHAIN_API_KEY", raising=False)
    monkeypatch.delenv("LANGCHAIN_PROJECT", raising=False)

    assert configure_langsmith() is False


def test_langsmith_tracing_sets_default_project(monkeypatch):
    monkeypatch.setenv("LANGCHAIN_TRACING_V2", "true")
    monkeypatch.setenv("LANGCHAIN_API_KEY", "test-key")
    monkeypatch.delenv("LANGCHAIN_PROJECT", raising=False)

    assert configure_langsmith() is True
    assert __import__("os").environ["LANGCHAIN_PROJECT"] == "askyourdb"