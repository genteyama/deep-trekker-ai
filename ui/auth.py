from __future__ import annotations

from dataclasses import dataclass
import logging
from typing import Callable, Optional

import streamlit as st

from repositories.actor import AUTH_EMAIL_KEY
from repositories.settings import get_setting

logger = logging.getLogger(__name__)

AUTH_SETTINGS = ("SUPABASE_URL", "SUPABASE_ANON_KEY", "ALLOWED_EMAILS")


@dataclass(frozen=True)
class LoginResult:
    ok: bool
    email: Optional[str] = None
    reason: Optional[str] = None


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


def require_login() -> bool:
    """Returns True when the app may render business content for this browser session."""
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
            logout()
            st.rerun()
