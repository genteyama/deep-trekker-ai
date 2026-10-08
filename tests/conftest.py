import pytest


@pytest.fixture(autouse=True)
def isolate_sqlite(tmp_path, monkeypatch):
    monkeypatch.setenv("DEEP_TREKKER_SQLITE", str(tmp_path / "test.sqlite3"))
    # Tests never reach a real central database or Supabase, even if the developer has them configured.
    for name in ("DATABASE_URL", "SUPABASE_URL", "SUPABASE_ANON_KEY", "ALLOWED_EMAILS"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setattr("repositories.settings._read_st_secret", lambda name: None)


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
