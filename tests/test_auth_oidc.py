from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

from repositories.actor import AUTH_EMAIL_KEY
from ui import auth


NOW = datetime(2026, 10, 11, 3, 0, tzinfo=timezone.utc)
ALLOWED_EMAIL = "allowed@example.com"


class FakeStreamlit:
    def __init__(self, user=None, *, login_clicked=False, logout_clicked=False):
        self.user = user or SimpleNamespace(is_logged_in=False)
        self.session_state = {}
        self.login_clicked = login_clicked
        self.logout_clicked = logout_clicked
        self.login_calls = 0
        self.logout_calls = 0
        self.errors = []
        self.titles = []
        self.captions = []
        self.sidebar = self

    def __enter__(self):
        return self

    def __exit__(self, _exc_type, _exc_value, _traceback):
        return False

    def title(self, value):
        self.titles.append(value)

    def button(self, label, **_kwargs):
        if label == "Googleアカウントでログイン":
            return self.login_clicked
        if label == "ログアウト":
            return self.logout_clicked
        return False

    def login(self):
        self.login_calls += 1

    def logout(self):
        self.logout_calls += 1

    def error(self, value):
        self.errors.append(value)

    def caption(self, value):
        self.captions.append(value)


def _user(*, email=ALLOWED_EMAIL, email_verified=True, iat=None):
    return SimpleNamespace(
        is_logged_in=True,
        email=email,
        email_verified=email_verified,
        iat=NOW.timestamp() if iat is None else iat,
    )


@pytest.mark.parametrize(
    ("setting", "expected"),
    [
        (None, auth.AUTH_MODE_LEGACY),
        ("legacy", auth.AUTH_MODE_LEGACY),
        ("google_oidc", auth.AUTH_MODE_GOOGLE_OIDC),
    ],
)
def test_auth_mode_dispatches_supported_values(monkeypatch, setting, expected):
    monkeypatch.setattr(auth, "get_setting", lambda name: setting if name == "AUTH_MODE" else None)
    assert auth.auth_mode() == expected


def test_invalid_auth_mode_is_configuration_error_and_fails_closed(monkeypatch):
    fake_st = FakeStreamlit()
    monkeypatch.setattr(auth, "st", fake_st)
    monkeypatch.setattr(auth, "get_setting", lambda name: "invalid" if name == "AUTH_MODE" else None)

    assert auth.require_login() is False
    assert fake_st.errors == [auth._AUTH_CONFIGURATION_MESSAGE]


def test_oidc_not_logged_in_shows_google_login_only(monkeypatch):
    fake_st = FakeStreamlit()
    monkeypatch.setattr(auth, "st", fake_st)

    assert auth._require_oidc_login() is False
    assert fake_st.titles == ["Deep Trekker AI"]
    assert fake_st.login_calls == 0
    assert AUTH_EMAIL_KEY not in fake_st.session_state


def test_oidc_login_button_uses_native_streamlit_login(monkeypatch):
    fake_st = FakeStreamlit(login_clicked=True)
    monkeypatch.setattr(auth, "st", fake_st)

    assert auth._require_oidc_login() is False
    assert fake_st.login_calls == 1


def test_valid_oidc_claims_set_existing_actor_email(monkeypatch):
    fake_st = FakeStreamlit(_user(iat=(NOW - timedelta(hours=1)).timestamp()))
    monkeypatch.setattr(auth, "st", fake_st)
    monkeypatch.setattr(auth, "_utc_now", lambda: NOW)
    monkeypatch.setattr(auth, "is_allowed", lambda email: email == ALLOWED_EMAIL)

    assert auth._require_oidc_login() is True
    assert fake_st.session_state[AUTH_EMAIL_KEY] == ALLOWED_EMAIL


@pytest.mark.parametrize(
    "user",
    [
        _user(email=None),
        _user(email=" "),
        _user(email_verified=False),
        _user(email_verified="true"),
        SimpleNamespace(is_logged_in=True, email=ALLOWED_EMAIL, email_verified=True),
        _user(iat="not-a-timestamp"),
        _user(iat=float("nan")),
        _user(iat=datetime(2026, 10, 11, 2, 0)),
    ],
)
def test_invalid_oidc_claims_fail_closed(monkeypatch, user):
    monkeypatch.setattr(auth, "is_allowed", lambda _email: True)
    result = auth._validate_oidc_user(user, now=NOW)
    assert result.ok is False
    assert result.reason == "invalid_claims"


@pytest.mark.parametrize("iat", [int(NOW.timestamp()), float(NOW.timestamp()), str(NOW.timestamp())])
def test_iat_accepts_unix_numeric_forms(monkeypatch, iat):
    monkeypatch.setattr(auth, "is_allowed", lambda _email: True)
    assert auth._validate_oidc_user(_user(iat=iat), now=NOW).ok is True


@pytest.mark.parametrize(
    ("age", "expected", "reason"),
    [
        (timedelta(hours=11, minutes=59), True, None),
        (timedelta(hours=12), False, "expired"),
        (timedelta(hours=12, seconds=1), False, "expired"),
    ],
)
def test_oidc_absolute_timeout_boundary(monkeypatch, age, expected, reason):
    monkeypatch.setattr(auth, "is_allowed", lambda _email: True)
    result = auth._validate_oidc_user(_user(iat=(NOW - age).timestamp()), now=NOW)
    assert result.ok is expected
    assert result.reason == reason


def test_oidc_user_must_remain_in_allowed_emails(monkeypatch):
    monkeypatch.setattr(auth, "is_allowed", lambda _email: False)
    result = auth._validate_oidc_user(_user(), now=NOW)
    assert result.ok is False
    assert result.reason == "not_allowed"


def test_oidc_logout_clears_business_session_then_calls_native_logout(monkeypatch):
    fake_st = FakeStreamlit()
    fake_st.session_state.update({AUTH_EMAIL_KEY: ALLOWED_EMAIL, "quote_draft": "sensitive"})
    monkeypatch.setattr(auth, "st", fake_st)

    auth._logout_oidc()

    assert fake_st.session_state == {}
    assert fake_st.logout_calls == 1


def test_oidc_sidebar_logout_uses_native_logout(monkeypatch):
    fake_st = FakeStreamlit(logout_clicked=True)
    fake_st.session_state[AUTH_EMAIL_KEY] = ALLOWED_EMAIL
    monkeypatch.setattr(auth, "st", fake_st)
    monkeypatch.setattr(auth, "auth_mode", lambda: auth.AUTH_MODE_GOOGLE_OIDC)

    auth.render_identity()

    assert fake_st.captions == [f"ログイン中：{ALLOWED_EMAIL}"]
    assert fake_st.session_state == {}
    assert fake_st.logout_calls == 1
