import pytest


@pytest.fixture(autouse=True)
def isolate_sqlite(tmp_path, monkeypatch):
    monkeypatch.setenv("DEEP_TREKKER_SQLITE", str(tmp_path / "test.sqlite3"))


@pytest.fixture(autouse=True)
def default_technical_case_provider(monkeypatch):
    monkeypatch.setenv("TECHNICAL_CASE_PROVIDER", "mock")
    monkeypatch.setenv("ANTHROPIC_ENABLE_FALLBACKS", "false")
    monkeypatch.setenv("GEMINI_API_KEY", "")


@pytest.fixture(autouse=True)
def reset_provider_runtime():
    from llm.provider import reset_runtime_status

    reset_runtime_status()
    yield
    reset_runtime_status()
