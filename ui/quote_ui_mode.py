"""Which quote screen the 見積作成 page shows.

The one-screen builder (PORTAL-3B.1) is the default. The legacy 5-step workspace stays available for
SPECTRA quotes and for drafts that were not made by the builder; it is reached from inside the page,
never as a second navigation entry.
"""

from __future__ import annotations

QUOTE_UI_MODE_KEY = "quote_ui_mode"
QUOTE_UI_SIMPLE = "simple"
QUOTE_UI_LEGACY = "legacy"


def use_legacy_quote_ui(session) -> bool:
    from agents.simple_quote_builder import is_simple_draft

    from ui.quote_handoff import SESSION_QUOTE_HANDOFF_CASE_ID, SOURCE_CASE_ID

    if session.get(SESSION_QUOTE_HANDOFF_CASE_ID) or session.get(SOURCE_CASE_ID):
        # Technical Case → quote handoff pre-fills the legacy general entry form; stay there afterwards.
        session[QUOTE_UI_MODE_KEY] = QUOTE_UI_LEGACY
        return True
    draft = session.get("quote_draft")
    if draft is not None:
        # An open draft decides by itself: builder drafts always use the builder, others the legacy screen.
        return not is_simple_draft(draft)
    return session.get(QUOTE_UI_MODE_KEY) == QUOTE_UI_LEGACY
