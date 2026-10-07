from agents.quote_builder import apply_exchange_rate
from models import ExchangeRateReason
from repositories.sqlite_quote_repository import SqliteQuoteRepository
from tests.test_exchange_rate_safety import _no_official_files, _open_quote_page
from tests.test_quote_approval import _ready_photon
from ui.quote_steps import (
    FX_METADATA_KEYS,
    SESSION_FX_EDITOR,
    SESSION_QUOTE_STEP,
    exchange_rate_editor_values,
    sync_exchange_rate_editor,
)

METADATA_A = {
    "reason_code": ExchangeRateReason.MARKET_PLUS_BUFFER,
    "reason_note": "市場＋3円",
    "set_by": "弦",
    "market_reference_rate": 162.0,
    "market_reference_date": "2026-10-01",
    "market_reference_source": "TTS",
    "exchange_rate_buffer": 3.0,
}
METADATA_B = {
    "reason_code": ExchangeRateReason.LONG_TERM_PROJECT,
    "reason_note": "長期案件",
    "set_by": "佐藤",
    "market_reference_rate": 158.5,
    "market_reference_date": "2026-09-15",
    "market_reference_source": "社内レート",
    "exchange_rate_buffer": 11.5,
}
EXPECTED_A = {
    SESSION_FX_EDITOR: "165",
    FX_METADATA_KEYS["exchange_rate_reason_code"]: "MARKET_PLUS_BUFFER",
    FX_METADATA_KEYS["exchange_rate_reason_note"]: "市場＋3円",
    FX_METADATA_KEYS["exchange_rate_set_by"]: "弦",
    FX_METADATA_KEYS["market_reference_rate"]: "162",
    FX_METADATA_KEYS["market_reference_date"]: "2026-10-01",
    FX_METADATA_KEYS["market_reference_source"]: "TTS",
    FX_METADATA_KEYS["exchange_rate_buffer"]: "3",
}
EXPECTED_B = {
    SESSION_FX_EDITOR: "170",
    FX_METADATA_KEYS["exchange_rate_reason_code"]: "LONG_TERM_PROJECT",
    FX_METADATA_KEYS["exchange_rate_reason_note"]: "長期案件",
    FX_METADATA_KEYS["exchange_rate_set_by"]: "佐藤",
    FX_METADATA_KEYS["market_reference_rate"]: "158.50",
    FX_METADATA_KEYS["market_reference_date"]: "2026-09-15",
    FX_METADATA_KEYS["market_reference_source"]: "社内レート",
    FX_METADATA_KEYS["exchange_rate_buffer"]: "11.50",
}
REASON_KEY = FX_METADATA_KEYS["exchange_rate_reason_code"]


def _widget_values(at) -> dict:
    values = {key: at.text_input(key=key).value for key in EXPECTED_A if key != REASON_KEY}
    values[REASON_KEY] = at.selectbox(key=REASON_KEY).value
    return values


def _saved_draft(rate, metadata, draft_id=None):
    draft = _ready_photon()
    if draft_id:
        draft.quote_draft_id = draft_id
    apply_exchange_rate(draft, rate, **metadata)
    SqliteQuoteRepository().save_draft(draft)
    return draft


def _resume(at, draft_id):
    next(item for item in at.button if (item.key or "").startswith(f"resume_draft_{draft_id}_")).click().run()
    at.session_state[SESSION_QUOTE_STEP] = 2
    at.run()
    assert not at.exception


def _go_to_step(at, step):
    at.button(key=f"quote_step_{step}").click().run()
    assert not at.exception
    assert at.session_state[SESSION_QUOTE_STEP] == step


def _stored(draft_id):
    loaded = SqliteQuoteRepository().get_draft(draft_id)
    return loaded.draft.model_dump(mode="json"), loaded.updated_at, loaded.content_hash, loaded.ui_state


def _costs(draft):
    return [
        (line.dealer_cost_jpy, line.landed_cost_jpy, line.standard_sales_price_candidate_jpy, line.final_sales_price_jpy)
        for line in draft.configuration_lines
    ]


def _apply_in_ui(at, rate, widgets):
    at.text_input(key=SESSION_FX_EDITOR).set_value(rate)
    for key, value in widgets.items():
        if key == REASON_KEY:
            at.selectbox(key=key).set_value(value)
        elif key != SESSION_FX_EDITOR:
            at.text_input(key=key).set_value(value)
    at.button(key="apply_quote_exchange_rate").click().run()
    assert not at.exception


def test_saved_fx_metadata_is_restored_after_leaving_step_2(tmp_path, monkeypatch):
    _no_official_files(tmp_path, monkeypatch)
    at = _open_quote_page()
    at.button(key="ihi_photon_draft").click().run()
    at.session_state[SESSION_QUOTE_STEP] = 2
    at.run()
    _apply_in_ui(at, "165", EXPECTED_A)
    draft_id = at.session_state["quote_draft"].quote_draft_id
    assert _widget_values(at) == EXPECTED_A

    _go_to_step(at, 3)
    _go_to_step(at, 2)
    assert _widget_values(at) == EXPECTED_A
    context = at.session_state["quote_draft"].pricing_context
    assert context.exchange_rate_reason_code == ExchangeRateReason.MARKET_PLUS_BUFFER

    # The first Step 3 visit stores its own ui_state; from here on only the Step 2 restore is measured.
    stored_before = _stored(draft_id)
    costs_before = _costs(at.session_state["quote_draft"])
    _go_to_step(at, 3)
    _go_to_step(at, 2)

    assert _widget_values(at) == EXPECTED_A
    # Showing the step again only restores the editor: nothing is applied, recalculated or changed in the DB.
    # (Moving between steps stores the current step in ui_state, so only the hash is compared across the round trip.)
    payload, _, digest, _ = _stored(draft_id)
    assert (payload, digest) == (stored_before[0], stored_before[2])
    assert _costs(at.session_state["quote_draft"]) == costs_before
    restored = _stored(draft_id)
    at.run()
    at.run()
    assert _widget_values(at) == EXPECTED_A
    assert _stored(draft_id) == restored

    # Changing only the rate keeps the restored decision metadata.
    at.text_input(key=SESSION_FX_EDITOR).set_value("170")
    at.button(key="apply_quote_exchange_rate").click().run()
    assert not at.exception
    saved = SqliteQuoteRepository().get_draft(draft_id).draft
    assert saved.exchange_rate == 170.0
    assert saved.pricing_context.exchange_rate_reason_code == ExchangeRateReason.MARKET_PLUS_BUFFER
    for field, value in METADATA_A.items():
        name = field if field.startswith(("market_", "exchange_")) else f"exchange_rate_{field}"
        assert getattr(saved.pricing_context, name) == value


def test_unsaved_input_survives_rerun_on_the_same_step(tmp_path, monkeypatch):
    _no_official_files(tmp_path, monkeypatch)
    draft = _saved_draft(165, METADATA_A)
    at = _open_quote_page()
    _resume(at, draft.quote_draft_id)
    assert _widget_values(at) == EXPECTED_A

    at.text_input(key=SESSION_FX_EDITOR).set_value("170").run()
    at.text_input(key=FX_METADATA_KEYS["exchange_rate_reason_note"]).set_value("入力途中").run()
    at.run()

    assert at.text_input(key=SESSION_FX_EDITOR).value == "170"
    assert at.text_input(key=FX_METADATA_KEYS["exchange_rate_reason_note"]).value == "入力途中"
    assert SqliteQuoteRepository().get_draft(draft.quote_draft_id).draft.exchange_rate == 165.0


def test_switching_quotes_shows_each_quotes_saved_fx_values(tmp_path, monkeypatch):
    _no_official_files(tmp_path, monkeypatch)
    quote_a = _saved_draft(165, METADATA_A)
    quote_b = _saved_draft(170, METADATA_B, draft_id="quote-b")
    at = _open_quote_page()

    _resume(at, quote_a.quote_draft_id)
    assert _widget_values(at) == EXPECTED_A
    _go_to_step(at, 3)
    at = _open_quote_page()
    _resume(at, quote_b.quote_draft_id)
    assert _widget_values(at) == EXPECTED_B
    _go_to_step(at, 3)
    at = _open_quote_page()
    _resume(at, quote_a.quote_draft_id)
    assert _widget_values(at) == EXPECTED_A


def test_switching_quotes_in_one_session_does_not_carry_fx_state():
    quote_a = _ready_photon()
    apply_exchange_rate(quote_a, 165, **METADATA_A)
    quote_b = _ready_photon()
    apply_exchange_rate(quote_b, 170, **METADATA_B)
    session = {}

    sync_exchange_rate_editor(session, quote_a)
    session[FX_METADATA_KEYS["exchange_rate_reason_note"]] = "Aの入力途中"
    sync_exchange_rate_editor(session, quote_b)
    assert {key: session[key] for key in EXPECTED_B} == EXPECTED_B
    for key in EXPECTED_A:
        session.pop(key)  # widgets dropped while another step was shown
    sync_exchange_rate_editor(session, quote_a)
    assert {key: session[key] for key in EXPECTED_A} == EXPECTED_A


def test_missing_keys_are_refilled_without_overwriting_present_input():
    draft = _ready_photon()
    apply_exchange_rate(draft, 165, **METADATA_A)
    session = {}
    sync_exchange_rate_editor(session, draft)
    session[SESSION_FX_EDITOR] = "170"
    for key in list(EXPECTED_A)[1:]:
        session.pop(key)

    sync_exchange_rate_editor(session, draft)

    assert session[SESSION_FX_EDITOR] == "170"
    assert {key: session[key] for key in list(EXPECTED_A)[1:]} == dict(list(EXPECTED_A.items())[1:])


def test_legacy_draft_without_fx_metadata_renders_empty_fields():
    draft = _ready_photon()  # saved at 170 before any decision metadata was recorded
    assert draft.pricing_context.exchange_rate_reason_code is None
    values = exchange_rate_editor_values(draft)
    assert values[SESSION_FX_EDITOR] == "170"
    assert all(values[key] == "" for key in FX_METADATA_KEYS.values())

    SqliteQuoteRepository().save_draft(draft)
    at = _open_quote_page()
    _resume(at, draft.quote_draft_id)
    _go_to_step(at, 3)
    _go_to_step(at, 2)
    shown = _widget_values(at)
    assert shown[SESSION_FX_EDITOR] == "170"
    assert all(shown[key] == "" for key in FX_METADATA_KEYS.values())
    visible = " ".join(item.value for item in at.markdown) + " ".join(item.value for item in at.caption)
    assert "None" not in visible
