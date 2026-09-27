import pytest


@pytest.fixture(autouse=True)
def isolate_sqlite(tmp_path, monkeypatch):
    monkeypatch.setenv("DEEP_TREKKER_SQLITE", str(tmp_path / "test.sqlite3"))
