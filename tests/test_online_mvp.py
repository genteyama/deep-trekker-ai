import hashlib
from pathlib import Path
import sqlite3
import subprocess
from types import SimpleNamespace

import pytest
from streamlit.testing.v1 import AppTest

from agents.price_master import materialize_stored_file
from agents.technical_case_persistence import build_record
from models import ActivityEvent, PriceMasterImport
from repositories.actor import set_current_actor
from repositories.postgres import PostgresConnection, translate_sql
from repositories.quote_repository import CONFLICT_MESSAGE, ConcurrentUpdateError
from repositories.sqlite import connect_sqlite, default_sqlite_path
from repositories.sqlite_activity_repository import SqliteActivityRepository
from repositories.sqlite_quote_repository import SqliteQuoteRepository
from repositories.sqlite_technical_case_repository import SqliteTechnicalCaseRepository
from repositories.technical_case_repository import TechnicalCaseConflictError
from tests.test_quote_approval import _approve, _ready_photon
from tests.test_quote_builder import _photon_draft
from tests.test_technical_case_persistence import _analyze

ROOT = Path(__file__).resolve().parents[1]
APP_PATH = ROOT / "app.py"
BUSINESS_TEXT = "進行中の案件"


@pytest.fixture(autouse=True)
def reset_actor():
    set_current_actor(None)
    yield
    set_current_actor(None)


@pytest.fixture
def online_auth(monkeypatch):
    monkeypatch.setenv("SUPABASE_URL", "https://example.invalid")
    monkeypatch.setenv("SUPABASE_ANON_KEY", "placeholder-anon-key")
    monkeypatch.setenv("ALLOWED_EMAILS", "allowed@example.com,second@example.com")


def _fake_client_factory(email):
    calls = {"signed_out": False}

    def factory(url, key):
        def sign_in_with_password(credentials):
            return SimpleNamespace(user=SimpleNamespace(email=email))

        def sign_out():
            calls["signed_out"] = True

        return SimpleNamespace(auth=SimpleNamespace(sign_in_with_password=sign_in_with_password, sign_out=sign_out))

    return factory, calls


def _visible(at: AppTest) -> str:
    return " ".join(
        [item.value for item in at.markdown]
        + [item.value for item in at.caption]
        + [item.value for item in at.title]
        + [item.value for item in at.error]
    )


def _login(at: AppTest, email: str) -> AppTest:
    at.text_input(key="login_email").input(email)
    at.text_input(key="login_password").input("not-a-real-password")
    at.button[0].click().run()
    return at


# 1. unauthenticated -> application content inaccessible
def test_unauthenticated_user_sees_only_login(online_auth):
    at = AppTest.from_file(str(APP_PATH)).run()
    text = _visible(at)
    assert "Deep Trekker AI" in text
    assert BUSINESS_TEXT not in text
    assert [item.label for item in at.text_input] == ["Email", "Password"]


# 2. allowed login
def test_allowed_login_shows_app_and_identity(online_auth, monkeypatch):
    factory, _calls = _fake_client_factory("allowed@example.com")
    monkeypatch.setattr("ui.auth._create_client", factory)
    at = _login(AppTest.from_file(str(APP_PATH)).run(), "allowed@example.com")
    text = _visible(at)
    assert "ログイン中：allowed@example.com" in text
    assert BUSINESS_TEXT in text
    assert any(button.label == "ログアウト" for button in at.button)
    assert "not-a-real-password" not in str(dict(at.session_state.filtered_state))


# 3. disallowed email denied
def test_disallowed_email_is_denied(online_auth, monkeypatch):
    factory, calls = _fake_client_factory("intruder@example.com")
    monkeypatch.setattr("ui.auth._create_client", factory)
    at = _login(AppTest.from_file(str(APP_PATH)).run(), "intruder@example.com")
    text = _visible(at)
    assert "利用権限がありません" in text
    assert BUSINESS_TEXT not in text
    assert "auth_email" not in at.session_state
    assert calls["signed_out"] is True


def test_online_settings_without_supabase_fail_closed(monkeypatch):
    monkeypatch.setenv("ALLOWED_EMAILS", "allowed@example.com")
    at = AppTest.from_file(str(APP_PATH)).run()
    assert BUSINESS_TEXT not in _visible(at)


# 4. actor identity propagation
def test_actor_identity_is_recorded(tmp_path):
    db = tmp_path / "actor.sqlite3"
    set_current_actor("allowed@example.com")
    cases = SqliteTechnicalCaseRepository(db)
    record = build_record(_analyze())
    cases.save_case(record)
    set_current_actor("second@example.com")
    cases.save_case(cases.get_case(record.case_id))

    quotes = SqliteQuoteRepository(db)
    draft = _ready_photon()
    quotes.save_draft(draft)
    _approval, snapshot = _approve(draft)
    quotes.save_snapshot(snapshot)
    SqliteActivityRepository(db).append(
        ActivityEvent(
            event_id="", occurred_at="", event_type="TEST", entity_kind="technical_case", entity_id=record.case_id
        )
    )

    raw = sqlite3.connect(db)
    assert raw.execute("SELECT created_by, updated_by, row_version FROM technical_cases").fetchone() == (
        "allowed@example.com",
        "second@example.com",
        2,
    )
    assert raw.execute("SELECT created_by, updated_by FROM quote_drafts").fetchone() == ("second@example.com",) * 2
    assert raw.execute("SELECT approved_by FROM approved_quote_snapshots").fetchone() == ("second@example.com",)
    assert raw.execute("SELECT actor_email FROM activity_events").fetchone() == ("second@example.com",)


# 5. optimistic lock success / C. other user sees the update after reload
def test_optimistic_lock_success_and_visibility(tmp_path):
    db = tmp_path / "shared.sqlite3"
    user_a = SqliteTechnicalCaseRepository(db)
    user_b = SqliteTechnicalCaseRepository(db)
    record = build_record(_analyze())
    user_a.save_case(record)

    loaded = user_a.get_case(record.case_id)
    result = user_a.save_case(loaded.model_copy(update={"case_title": "A edit"}))
    assert result.row_version == 2
    assert user_b.get_case(record.case_id).case_title == "A edit"
    again = user_a.save_case(user_a.get_case(record.case_id).model_copy(update={"case_title": "A edit 2"}))
    assert again.row_version == 3


# 6. optimistic lock conflict rejects overwrite (technical case)
def test_technical_case_conflict_keeps_first_save(tmp_path):
    db = tmp_path / "shared.sqlite3"
    user_a = SqliteTechnicalCaseRepository(db)
    user_b = SqliteTechnicalCaseRepository(db)
    record = build_record(_analyze())
    user_a.save_case(record)

    loaded_a = user_a.get_case(record.case_id)
    loaded_b = user_b.get_case(record.case_id)
    user_a.save_case(loaded_a.model_copy(update={"case_title": "A wins"}))
    with pytest.raises(TechnicalCaseConflictError) as error:
        user_b.save_case(loaded_b.model_copy(update={"case_title": "B stale"}))
    assert str(error.value) == CONFLICT_MESSAGE
    assert SqliteTechnicalCaseRepository(db).get_case(record.case_id).case_title == "A wins"

    # Reload, then B may save on top of A's version.
    user_b.forget_row_version(record.case_id)
    reloaded = user_b.get_case(record.case_id)
    user_b.save_case(reloaded.model_copy(update={"case_title": "B after reload"}))
    assert user_a.get_case(record.case_id).case_title == "B after reload"


def test_quote_draft_conflict_keeps_first_save(tmp_path):
    db = tmp_path / "shared.sqlite3"
    user_a = SqliteQuoteRepository(db)
    user_b = SqliteQuoteRepository(db)
    draft = _photon_draft()
    user_a.save_draft(draft)

    loaded_a = user_a.get_draft(draft.quote_draft_id, draft.quote_version)
    loaded_b = user_b.get_draft(draft.quote_draft_id, draft.quote_version)
    assert loaded_a.row_version == loaded_b.row_version == 1
    user_a.save_draft(loaded_a.draft.model_copy(update={"title": "A wins"}), force=True)
    with pytest.raises(ConcurrentUpdateError):
        user_b.save_draft(loaded_b.draft.model_copy(update={"title": "B stale"}), force=True)
    # Autosave (get_draft before save) must not refresh B's base version either.
    user_b.get_draft(draft.quote_draft_id, draft.quote_version)
    with pytest.raises(ConcurrentUpdateError):
        user_b.save_draft(loaded_b.draft.model_copy(update={"title": "B stale"}))
    stored = SqliteQuoteRepository(db).get_draft(draft.quote_draft_id, draft.quote_version)
    assert stored.draft.title == "A wins"
    assert stored.row_version == 2


# 7. Approved snapshot remains immutable
def test_approved_snapshot_is_immutable(tmp_path):
    repo = SqliteQuoteRepository(tmp_path / "snap.sqlite3")
    draft = _ready_photon()
    _approval, snapshot = _approve(draft)
    assert repo.save_snapshot(snapshot) is True
    before = repo.get_snapshot(snapshot.approved_quote_snapshot_id).model_dump(mode="json")
    changed = snapshot.model_copy(update={"total_jpy": 1})
    assert repo.save_snapshot(changed) is False
    assert repo.get_snapshot(snapshot.approved_quote_snapshot_id).model_dump(mode="json") == before


# 8. SQLite fallback unchanged
def test_sqlite_is_default_without_database_url():
    assert isinstance(connect_sqlite(), sqlite3.Connection)
    assert isinstance(SqliteQuoteRepository()._connection, sqlite3.Connection)


def test_database_url_selects_postgres_only_for_default_db(monkeypatch, tmp_path):
    monkeypatch.setenv("DATABASE_URL", "postgresql://placeholder.invalid/db")
    assert isinstance(connect_sqlite(), PostgresConnection)
    assert isinstance(connect_sqlite(default_sqlite_path()), PostgresConnection)
    assert isinstance(connect_sqlite(tmp_path / "explicit.sqlite3"), sqlite3.Connection)


def test_sql_translation_for_postgres():
    assert translate_sql("SELECT * FROM t WHERE a = ? AND IFNULL(s, '') LIKE '5%'") == (
        "SELECT * FROM t WHERE a = %s AND COALESCE(s, '') LIKE '5%%'"
    )
    assert translate_sql("ORDER BY customer_name COLLATE NOCASE") == "ORDER BY lower(customer_name)"


# 9. Price Master blob SHA / materialization
class _CentralRepo:
    is_central = True

    def __init__(self, root, blobs):
        self.storage_root = root
        self.blobs = blobs

    def get_file_bytes(self, import_id):
        return self.blobs.get(import_id)


def _record(import_id, data, sha=None):
    return PriceMasterImport(
        import_id=import_id,
        master_type="DT40",
        source_type="FILE_UPLOAD",
        original_filename="dt40.xlsx",
        stored_path=f"DT40/{import_id}.xlsx",
        sha256=sha or hashlib.sha256(data).hexdigest(),
        size_bytes=len(data),
        imported_at="2026-10-08T00:00:00+00:00",
        validation_status="VALID",
    )


def test_central_price_master_materializes_with_sha(tmp_path):
    data = b"PK\x03\x04central-workbook"
    record = _record("DT40-central", data)
    path = materialize_stored_file(_CentralRepo(tmp_path, {"DT40-central": data}), record)
    assert path == tmp_path / "DT40" / "DT40-central.xlsx"
    assert hashlib.sha256(path.read_bytes()).hexdigest() == record.sha256


def test_central_price_master_sha_mismatch_is_not_materialized(tmp_path):
    data = b"PK\x03\x04tampered"
    record = _record("DT40-bad", data, sha="0" * 64)
    path = materialize_stored_file(_CentralRepo(tmp_path, {"DT40-bad": data}), record)
    assert not path.exists()


# 10. no secrets committed
def test_no_secrets_committed():
    tracked = subprocess.run(["git", "ls-files"], cwd=ROOT, capture_output=True, text=True, check=True).stdout.split()
    assert ".streamlit/secrets.toml" not in tracked
    assert ".env" not in tracked
    example = (ROOT / ".streamlit" / "secrets.toml.example").read_text(encoding="utf-8")
    assert "YOUR-SUPABASE-ANON-KEY" in example and "YOUR-DB-PASSWORD" in example
    for name in tracked:
        path = ROOT / name
        if path.suffix not in {".py", ".toml", ".example", ".md", ".sql", ".txt", ".json"} or not path.is_file():
            continue
        text = path.read_text(encoding="utf-8", errors="ignore")
        # Needles are split so this file does not contain the tokens it scans for.
        for needle in ("eyJ" + "hbGciOi", "sb_" + "secret_"):
            assert needle not in text, name
