from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import logging
import math
from typing import Callable, Optional

import streamlit as st

from repositories.actor import AUTH_EMAIL_KEY
from repositories.settings import get_setting

logger = logging.getLogger(__name__)

AUTH_SETTINGS = ("SUPABASE_URL", "SUPABASE_ANON_KEY", "ALLOWED_EMAILS")
AUTH_MODE_LEGACY = "legacy"
AUTH_MODE_GOOGLE_OIDC = "google_oidc"
OIDC_SESSION_LIFETIME = timedelta(hours=12)


class AuthConfigurationError(ValueError):
    pass


@dataclass(frozen=True)
class LoginResult:
    ok: bool
    email: Optional[str] = None
    reason: Optional[str] = None


def auth_mode() -> str:
    mode = get_setting("AUTH_MODE")
    if mode is None:
        return AUTH_MODE_LEGACY
    if mode in {AUTH_MODE_LEGACY, AUTH_MODE_GOOGLE_OIDC}:
        return mode
    raise AuthConfigurationError("Unsupported AUTH_MODE")


def auth_required() -> bool:
    # Local v1 (no online settings) keeps working without login.
    # Any online setting turns login on; incomplete settings then fail closed.
    return any(get_setting(name) for name in (*AUTH_SETTINGS, "DATABASE_URL"))


def allowed_emails() -> set[str]:
    raw = get_setting("ALLOWED_EMAILS") or ""
    return {item.strip() for item in raw.split(",") if item.strip()}


def is_allowed(email: Optional[str]) -> bool:
    return bool(email) and email in allowed_emails()


def _create_client(url: str, key: str):
    from supabase import create_client

    return create_client(url, key)


def sign_in(email: str, password: str, client_factory: Optional[Callable] = None) -> LoginResult:
    url = get_setting("SUPABASE_URL")
    key = get_setting("SUPABASE_ANON_KEY")
    if not url or not key or not allowed_emails():
        return LoginResult(ok=False, reason="not_configured")
    client = (client_factory or _create_client)(url, key)
    try:
        response = client.auth.sign_in_with_password({"email": email, "password": password})
    except Exception:
        # Never log the password or the provider error payload.
        logger.warning("login_failed")
        return LoginResult(ok=False, reason="invalid_credentials")
    user = getattr(response, "user", None)
    authenticated = getattr(user, "email", None)
    if not authenticated:
        return LoginResult(ok=False, reason="invalid_credentials")
    if not is_allowed(authenticated):
        try:
            client.auth.sign_out()
        except Exception:
            pass
        logger.warning("login_denied_not_allowed")
        return LoginResult(ok=False, reason="not_allowed")
    return LoginResult(ok=True, email=authenticated)


def current_email() -> Optional[str]:
    return st.session_state.get(AUTH_EMAIL_KEY)


def logout() -> None:
    st.session_state.clear()


_REASON_MESSAGES = {
    "not_configured": "ログイン設定が不完全です。管理者に連絡してください。",
    "invalid_credentials": "メールアドレスまたはパスワードが正しくありません。",
    "not_allowed": "このアカウントには利用権限がありません。",
}
_AUTH_CONFIGURATION_MESSAGE = "ログイン設定に問題があります。管理者に連絡してください。"
_OIDC_SESSION_MESSAGE = "ログインセッションが無効または期限切れです。再度ログインしてください。"


def require_login() -> bool:
    """Returns True when the app may render business content for this browser session."""
    try:
        mode = auth_mode()
    except AuthConfigurationError:
        st.error(_AUTH_CONFIGURATION_MESSAGE)
        return False
    if mode == AUTH_MODE_GOOGLE_OIDC:
        return _require_oidc_login()
    return _require_legacy_login()


def _require_legacy_login() -> bool:
    if not auth_required():
        return True
    email = current_email()
    if email and is_allowed(email):
        return True
    if email:
        # ALLOWED_EMAILS changed while logged in: drop the session.
        st.session_state.pop(AUTH_EMAIL_KEY, None)
    _render_login()
    return False


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _parse_iat(value) -> Optional[datetime]:
    if isinstance(value, bool):
        return None
    if isinstance(value, datetime):
        if value.tzinfo is None or value.utcoffset() is None:
            return None
        return value.astimezone(timezone.utc)
    if isinstance(value, str):
        value = value.strip()
        if not value:
            return None
        try:
            value = float(value)
        except ValueError:
            return None
    if not isinstance(value, (int, float)) or not math.isfinite(value):
        return None
    try:
        return datetime.fromtimestamp(value, tz=timezone.utc)
    except (OverflowError, OSError, ValueError):
        return None


def _oidc_claim(user, name: str):
    try:
        return user.get(name)
    except (AttributeError, TypeError):
        try:
            return getattr(user, name)
        except (AttributeError, TypeError):
            return None


def _validate_oidc_user(user, *, now: Optional[datetime] = None) -> LoginResult:
    email = _oidc_claim(user, "email")
    if not isinstance(email, str) or not email.strip():
        return LoginResult(ok=False, reason="invalid_claims")
    email = email.strip()
    if _oidc_claim(user, "email_verified") is not True:
        return LoginResult(ok=False, reason="invalid_claims")
    issued_at = _parse_iat(_oidc_claim(user, "iat"))
    if issued_at is None:
        return LoginResult(ok=False, reason="invalid_claims")
    checked_at = now or _utc_now()
    if checked_at.tzinfo is None or checked_at.utcoffset() is None:
        return LoginResult(ok=False, reason="invalid_claims")
    checked_at = checked_at.astimezone(timezone.utc)
    if issued_at > checked_at or checked_at >= issued_at + OIDC_SESSION_LIFETIME:
        return LoginResult(ok=False, reason="expired")
    if not is_allowed(email):
        return LoginResult(ok=False, reason="not_allowed")
    return LoginResult(ok=True, email=email)


def _render_oidc_login() -> None:
    st.title("Deep Trekker AI")
    if st.button("Googleアカウントでログイン", key="oidc_login"):
        try:
            st.login()
        except Exception:
            logger.warning("oidc_login_failed")
            st.error(_AUTH_CONFIGURATION_MESSAGE)


def _logout_oidc(message: Optional[str] = None) -> None:
    st.session_state.clear()
    if message:
        st.error(message)
    st.logout()


def _require_oidc_login() -> bool:
    try:
        logged_in = st.user.is_logged_in
    except Exception:
        logger.warning("oidc_configuration_invalid")
        st.error(_AUTH_CONFIGURATION_MESSAGE)
        return False
    if not logged_in:
        _render_oidc_login()
        return False
    result = _validate_oidc_user(st.user)
    if not result.ok:
        message = _REASON_MESSAGES["not_allowed"] if result.reason == "not_allowed" else _OIDC_SESSION_MESSAGE
        _logout_oidc(message)
        return False
    st.session_state[AUTH_EMAIL_KEY] = result.email
    return True


def _render_login() -> None:
    st.title("Deep Trekker AI")
    with st.form("login_form"):
        email = st.text_input("Email", key="login_email")
        password = st.text_input("Password", type="password", key="login_password")
        submitted = st.form_submit_button("ログイン")
    if submitted:
        result = sign_in((email or "").strip(), password or "")
        if result.ok:
            st.session_state[AUTH_EMAIL_KEY] = result.email
            st.session_state.pop("login_password", None)
            st.rerun()
        else:
            st.error(_REASON_MESSAGES.get(result.reason or "", _REASON_MESSAGES["invalid_credentials"]))


def render_identity() -> None:
    email = current_email()
    if not email:
        return
    with st.sidebar:
        st.caption(f"ログイン中：{email}")
        if st.button("ログアウト", key="auth_logout"):
            if auth_mode() == AUTH_MODE_GOOGLE_OIDC:
                _logout_oidc()
            else:
                logout()
                st.rerun()
