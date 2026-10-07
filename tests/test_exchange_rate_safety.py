from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest

from agents.pricing_policy import (
    DEFAULT_QUOTE_EXCHANGE_RATE,
    build_exchange_rate_scenario,
    parse_exchange_rate,
    round_customer_price_jpy,
    simulate_sales_price_candidates,
)
from agents.quote_approval import create_revision_draft, validate_for_approval
from agents.landed_cost import build_ihi_landed_cost_scenario, resolve_ihi_dealer_values
from agents.quote_builder import apply_exchange_rate, apply_final_price, build_ihi_quote_draft
from agents.work_lifecycle import derive_quote, duplicate_quote
from models import (
    ExchangeRateSource,
    FinalPriceStatus,
    PriceSourceType,
    QuoteDraftStatus,
    QuoteLineageType,
    SalesPriceCandidate,
)
from repositories.sqlite_quote_repository import SqliteQuoteRepository
from tests.test_price_source_safety import _development_photon_draft
from tests.test_pricing_policy import _load_policy_case
from tests.test_landed_cost import _sales
from tests.test_quote_builder import _landed, _photon_sales
from tests.test_quote_approval import _approve, _ready_photon
from ui.quote_steps import SESSION_FX_EDITOR, SESSION_NEW_QUOTE_FX, sync_exchange_rate_editor

STALE = "Standard sales price candidate does not match the quote exchange rate"

APP_PATH = Path(__file__).resolve().parents[1] / "app.py"


def _no_official_files(tmp_path, monkeypatch):
    # The per-test database starts with no active price masters, so no official file can be used.
    from agents.price_master import get_active_master
    from models import PriceMasterType

    assert all(get_active_master(master_type) is None for master_type in PriceMasterType)


def _open_quote_page() -> AppTest:
    at = AppTest.from_file(str(APP_PATH)).run()
    at.button(key="open_quote_control").click().run()
    return at


def _assert_costs_use_rate(draft, rate):
    assert draft.exchange_rate == rate
    assert draft.pricing_context.exchange_rate == rate
    for line in draft.configuration_lines:
        assert line.dealer_cost_jpy == round(line.dealer_price_usd * line.quantity * rate, 4)
        assert line.manufacturer_price_snapshot.exchange_rate == rate
    for line in draft.shipping_lines:
        assert line.exchange_rate == rate
        assert line.cost_jpy == round(line.quantity * line.rate_usd * rate, 4)
    assert all(item.exchange_rate == rate for item in draft.pricing_context.manufacturer_price_snapshots)


def test_default_rate_is_defined_once_and_validated():
    assert DEFAULT_QUOTE_EXCHANGE_RATE == 160.0
    assert parse_exchange_rate("165") == 165.0
    for bad in ("", " ", "0", "-5", "abc", None, "nan", "inf"):
        with pytest.raises(ValueError):
            parse_exchange_rate(bad)
    source = Path("ui/quote_control.py").read_text(encoding="utf-8")
    assert 'or "170"' not in source


def test_new_quote_uses_160_and_shows_it(tmp_path, monkeypatch):
    _no_official_files(tmp_path, monkeypatch)
    at = _open_quote_page()

    assert at.text_input(key=SESSION_NEW_QUOTE_FX).value == "160"
    at.button(key="ihi_photon_draft").click().run()

    assert not at.exception
    draft = at.session_state["quote_draft"]
    _assert_costs_use_rate(draft, 160.0)
    assert draft.pricing_context.exchange_rate_source == ExchangeRateSource.STANDARD_DEFAULT
    visible = " ".join(item.value for item in at.markdown)
    assert "為替レート：160円/USD（基準：通常試算）" in visible


def test_rate_change_recalculates_saves_and_resumes(tmp_path, monkeypatch):
    _no_official_files(tmp_path, monkeypatch)
    at = _open_quote_page()
    at.button(key="ihi_photon_draft").click().run()
    draft_id = at.session_state["quote_draft"].quote_draft_id
    at.session_state["quote_workspace_step"] = 2
    at.run()

    assert at.text_input(key=SESSION_FX_EDITOR).value == "160"
    at.text_input(key=SESSION_FX_EDITOR).set_value("165")
    at.button(key="apply_quote_exchange_rate").click().run()

    assert not at.exception
    changed = at.session_state["quote_draft"]
    _assert_costs_use_rate(changed, 165.0)
    assert changed.pricing_context.exchange_rate_source == ExchangeRateSource.MANUAL_OVERRIDE
    assert "為替レート：165円/USD（基準：手動変更）" in " ".join(item.value for item in at.markdown)
    assert at.text_input(key=SESSION_FX_EDITOR).value == "165"

    stored = SqliteQuoteRepository().get_draft(draft_id)
    assert stored.draft.exchange_rate == 165.0
    assert stored.draft.pricing_context.exchange_rate_source == ExchangeRateSource.MANUAL_OVERRIDE

    reopened = _open_quote_page()
    resume = next(item for item in reopened.button if (item.key or "").startswith(f"resume_draft_{draft_id}_"))
    resume.click().run()
    reopened.session_state["quote_workspace_step"] = 2
    reopened.run()

    assert not reopened.exception
    _assert_costs_use_rate(reopened.session_state["quote_draft"], 165.0)
    assert reopened.text_input(key=SESSION_FX_EDITOR).value == "165"
    assert reopened.text_input(key=SESSION_NEW_QUOTE_FX).value == "160"
    assert "為替レート：165円/USD（基準：手動変更）" in " ".join(item.value for item in reopened.markdown)


def test_display_and_calculation_use_the_same_rate():
    draft = _ready_photon()
    apply_exchange_rate(draft, 165)

    _assert_costs_use_rate(draft, 165.0)
    session = {}
    sync_exchange_rate_editor(session, draft)
    assert session[SESSION_FX_EDITOR] == "165"
    assert [line.final_sales_price_jpy for line in draft.configuration_lines] == [
        line.final_sales_price_jpy for line in _ready_photon().configuration_lines
    ]


def _costs(draft):
    return [
        (line.dealer_cost_jpy, line.import_tax_jpy, line.insurance_jpy, line.landed_cost_jpy)
        for line in draft.configuration_lines
    ] + [(line.cost_jpy, line.sales_price_candidate_jpy) for line in draft.shipping_lines]


def test_changing_back_to_the_original_rate_reproduces_existing_costs():
    draft = _ready_photon()
    before = _costs(draft)

    apply_exchange_rate(draft, 165)
    assert _costs(draft) != before
    apply_exchange_rate(draft, 170)

    assert _costs(draft) == before


def test_applying_the_unchanged_rate_is_a_no_op():
    draft = _ready_photon()
    draft.pricing_context.exchange_rate_source = None
    before = draft.model_dump()

    apply_exchange_rate(draft, "170")

    assert draft.model_dump() == before


def test_duplicate_and_derived_quotes_keep_the_source_rate():
    draft = _ready_photon()
    apply_exchange_rate(draft, 165)

    for copied in (duplicate_quote(draft), derive_quote(draft, relation_type=QuoteLineageType.CONFIGURATION_CHANGE.value)):
        assert copied.quote_draft_id != draft.quote_draft_id
        _assert_costs_use_rate(copied, 165.0)
        assert copied.pricing_context.exchange_rate_source == ExchangeRateSource.MANUAL_OVERRIDE
        apply_exchange_rate(copied, 160)
        _assert_costs_use_rate(copied, 160.0)
    _assert_costs_use_rate(draft, 165.0)


def test_approved_snapshot_keeps_the_rate_used_at_approval():
    draft = _ready_photon()
    apply_exchange_rate(draft, 165)
    _, snapshot = _approve(draft)

    assert snapshot.exchange_rate == 165.0
    assert snapshot.exchange_rate_source == ExchangeRateSource.MANUAL_OVERRIDE
    with pytest.raises(ValueError):
        apply_exchange_rate(draft, 160)
    assert snapshot.exchange_rate == 165.0

    revision = create_revision_draft(snapshot)
    assert revision.exchange_rate == 165.0
    assert revision.pricing_context.exchange_rate_source == ExchangeRateSource.MANUAL_OVERRIDE


def test_existing_170_draft_is_not_changed_to_160(tmp_path):
    draft = _ready_photon()
    draft.pricing_context.exchange_rate_source = None  # saved before the source was recorded
    repo = SqliteQuoteRepository(tmp_path / "quotes.sqlite3")
    repo.save_draft(draft)

    loaded = repo.get_draft(draft.quote_draft_id).draft
    assert loaded.exchange_rate == 170.0
    assert loaded.pricing_context.exchange_rate_source is None
    session = {}
    sync_exchange_rate_editor(session, loaded)
    assert session[SESSION_FX_EDITOR] == "170"


def test_existing_170_draft_resumes_at_170_in_the_ui():
    draft = _ready_photon()
    draft.pricing_context.exchange_rate_source = None
    SqliteQuoteRepository().save_draft(draft)

    at = _open_quote_page()
    next(item for item in at.button if (item.key or "").startswith(f"resume_draft_{draft.quote_draft_id}_")).click().run()
    at.session_state["quote_workspace_step"] = 2
    at.run()

    assert not at.exception
    assert at.session_state["quote_draft"].exchange_rate == 170.0
    assert at.text_input(key=SESSION_FX_EDITOR).value == "170"
    assert "為替レート：170円/USD（基準：保存済みの値（由来の記録なし））" in " ".join(item.value for item in at.markdown)


def test_ihi_golden_case_with_explicit_170_still_reproduces():
    sales = _photon_sales()
    scenario, _ = _landed("PHOTON", sales)
    explicit = build_ihi_quote_draft(
        "PHOTON", scenario, sales, exchange_rate_source=ExchangeRateSource.MANUAL_OVERRIDE
    )
    assert explicit.exchange_rate == 170.0
    assert explicit.pricing_context.exchange_rate_source == ExchangeRateSource.MANUAL_OVERRIDE

    draft = _ready_photon()
    _assert_costs_use_rate(draft, 170.0)
    assert draft.pricing_context.exchange_rate_source is None
    assert validate_for_approval(draft).can_approve is True
    _, snapshot = _approve(draft)
    assert snapshot.exchange_rate == 170.0
    assert snapshot.total_jpy == 7876000


def test_non_positive_rate_cannot_calculate_or_approve(tmp_path, monkeypatch):
    draft = _ready_photon()
    before = draft.model_dump()
    for bad in (0, -1, "", "abc"):
        with pytest.raises(ValueError):
            apply_exchange_rate(draft, bad)
    assert draft.model_dump() == before

    draft.exchange_rate = 0
    draft.status = QuoteDraftStatus.READY_FOR_APPROVAL
    result = validate_for_approval(draft)
    assert result.can_approve is False
    assert any("Exchange rate is not set" in item for item in result.critical_warnings)

    _no_official_files(tmp_path, monkeypatch)
    at = _open_quote_page()
    at.text_input(key=SESSION_NEW_QUOTE_FX).set_value("0").run()
    assert any("0より大きい数値" in item.value for item in at.error)
    at.button(key="ihi_photon_draft").click().run()
    assert not at.exception
    assert "quote_draft" not in at.session_state or at.session_state["quote_draft"] is None


def test_rate_160_does_not_promote_development_prices():
    draft = _development_photon_draft()
    apply_exchange_rate(draft, 160)

    assert all(
        line.manufacturer_price_snapshot.price_source_type == PriceSourceType.DEVELOPMENT_REFERENCE
        for line in draft.configuration_lines
    )
    assert draft.status == QuoteDraftStatus.REVIEW_REQUIRED
    assert validate_for_approval(draft).can_approve is False


def _candidate(sku, price, rate):
    return _sales(sku, price, rate).model_copy(
        update={"sales_price_candidate_id": f"spc-{sku}-{rate}", "source_reference": "PHOTON"}
    )


def _load_master_into(at: AppTest):
    # Standard sales candidates come only from the active SO_MASTER (+ DT40) in the price master registry.
    from agents.price_master import import_price_master
    from models import PriceMasterType
    from tests.price_book_fixtures import pricing_policy_manufacturer_book, pricing_policy_master_book

    import_price_master(PriceMasterType.SO_MASTER, "so.xlsx", pricing_policy_master_book().getvalue())
    import_price_master(PriceMasterType.DT40, "dt40.xlsx", pricing_policy_manufacturer_book().getvalue())


def _expected_candidate(rate, sku="9680-BASE"):
    spaceone, _, policies, preview = _load_policy_case()
    candidates = simulate_sales_price_candidates(preview, policies, build_exchange_rate_scenario(rate), spaceone.items)
    return next(item.raw_sales_price_jpy for item in candidates if item.manufacturer_sku == sku)


def _line(draft, sku="9680-BASE"):
    return next(line for line in draft.configuration_lines if line.manufacturer_sku == sku)


def test_quote_at_160_uses_standard_candidates_calculated_at_160(tmp_path, monkeypatch):
    _no_official_files(tmp_path, monkeypatch)
    at = _open_quote_page()
    _load_master_into(at)
    # A scenario run at 170 in the development panel must not leak into the quote.
    at.session_state["sales_price_candidates"] = [_candidate("9680-BASE", 3547764.0, 170.0)]
    at.run()
    at.button(key="ihi_photon_draft").click().run()

    assert not at.exception
    draft = at.session_state["quote_draft"]
    assert draft.exchange_rate == 160.0
    # The candidate keeps the raw policy value; the quote standard is the customer price in thousands.
    assert _expected_candidate(160.0) == 3339072.0
    assert _line(draft).standard_sales_price_candidate_jpy == 3339000.0


def test_rate_change_in_ui_recalculates_standard_candidates_at_the_new_rate(tmp_path, monkeypatch):
    _no_official_files(tmp_path, monkeypatch)
    at = _open_quote_page()
    _load_master_into(at)
    at.run()
    at.button(key="ihi_photon_draft").click().run()
    at.session_state["quote_workspace_step"] = 2
    at.run()
    at.text_input(key=SESSION_FX_EDITOR).set_value("165")
    at.button(key="apply_quote_exchange_rate").click().run()

    assert not at.exception
    draft = at.session_state["quote_draft"]
    _assert_costs_use_rate(draft, 165.0)
    assert _line(draft).standard_sales_price_candidate_jpy == round_customer_price_jpy(_expected_candidate(165.0))
    assert not any(STALE in item for item in _line(draft).warnings)


def test_rate_change_without_candidate_inputs_invalidates_old_candidates():
    draft = _ready_photon()
    line = _line(draft)
    assert line.standard_sales_price_candidate_jpy is not None

    apply_exchange_rate(draft, 165)

    assert line.standard_sales_price_candidate_jpy is None
    assert line.standard_sales_price_candidate_id is None
    assert any(STALE in item and "165" in item for item in line.warnings)
    apply_final_price(draft, line.line_id, FinalPriceStatus.USE_STANDARD_CANDIDATE)
    assert line.final_price_status == FinalPriceStatus.NOT_SET


def test_candidates_at_another_rate_cannot_enter_a_quote():
    sales = [_candidate("9680-BASE", 3547764.0, 170.0), _candidate("8459", 160548.0, 160.0)]
    scenario, _ = _landed("PHOTON", sales)
    scenario = scenario.model_copy(update={"exchange_rate": 160.0})
    draft = build_ihi_quote_draft("PHOTON", scenario, sales)

    assert _line(draft).standard_sales_price_candidate_jpy is None
    assert any(STALE in item for item in _line(draft).warnings)
    assert _line(draft, "8459").standard_sales_price_candidate_jpy == 161000.0

    draft.exchange_rate = 165.0
    stale = [_candidate("9680-BASE", 3339072.0, 160.0)]
    apply_exchange_rate(draft, 170, sales_candidates=stale)
    assert _line(draft).standard_sales_price_candidate_jpy is None


def test_final_prices_are_not_changed_by_a_rate_change():
    draft = _ready_photon()
    finals = [(line.final_sales_price_jpy, line.final_price_status) for line in draft.configuration_lines]
    customer = [(line.unit_price_jpy, line.amount_jpy) for line in draft.customer_lines]

    apply_exchange_rate(draft, 165)
    apply_exchange_rate(draft, 160, sales_candidates=[_candidate("9680-BASE", 1000.0, 160.0)])

    assert [(line.final_sales_price_jpy, line.final_price_status) for line in draft.configuration_lines] == finals
    assert [(line.unit_price_jpy, line.amount_jpy) for line in draft.customer_lines] == customer
    assert _line(draft).standard_sales_price_candidate_jpy == 1000.0


def test_provenance_follows_the_operation_not_the_value(tmp_path, monkeypatch):
    _no_official_files(tmp_path, monkeypatch)
    at = _open_quote_page()
    at.button(key="ihi_photon_draft").click().run()
    assert at.session_state["quote_draft"].pricing_context.exchange_rate_source == ExchangeRateSource.STANDARD_DEFAULT

    at.text_input(key=SESSION_NEW_QUOTE_FX).set_value("165").run()
    at.button(key="ihi_photon_draft").click().run()
    draft = at.session_state["quote_draft"]
    assert (draft.exchange_rate, draft.pricing_context.exchange_rate_source) == (165.0, ExchangeRateSource.MANUAL_OVERRIDE)

    at.text_input(key=SESSION_NEW_QUOTE_FX).set_value("160").run()
    at.button(key="ihi_photon_draft").click().run()
    draft = at.session_state["quote_draft"]
    assert (draft.exchange_rate, draft.pricing_context.exchange_rate_source) == (160.0, ExchangeRateSource.MANUAL_OVERRIDE)
    assert "基準：手動変更" in " ".join(item.value for item in at.markdown)


def test_manual_change_back_to_160_stays_manual():
    sales = _photon_sales()
    scenario, _ = _landed("PHOTON", sales)
    scenario = scenario.model_copy(update={"exchange_rate": 160.0})
    draft = build_ihi_quote_draft("PHOTON", scenario, sales, exchange_rate_source=ExchangeRateSource.STANDARD_DEFAULT)
    assert draft.pricing_context.exchange_rate_source == ExchangeRateSource.STANDARD_DEFAULT

    apply_exchange_rate(draft, 165)
    assert draft.pricing_context.exchange_rate_source == ExchangeRateSource.MANUAL_OVERRIDE
    apply_exchange_rate(draft, 160)
    assert draft.exchange_rate == 160.0
    assert draft.pricing_context.exchange_rate_source == ExchangeRateSource.MANUAL_OVERRIDE


def test_legacy_draft_without_source_is_not_given_one_from_its_value(tmp_path):
    for rate in (160.0, 170.0):
        sales = _photon_sales()
        scenario, _ = _landed("PHOTON", sales)
        scenario = scenario.model_copy(update={"exchange_rate": rate})
        draft = build_ihi_quote_draft("PHOTON", scenario, sales)
        repo = SqliteQuoteRepository(tmp_path / f"legacy-{int(rate)}.sqlite3")
        repo.save_draft(draft)
        loaded = repo.get_draft(draft.quote_draft_id).draft
        assert loaded.exchange_rate == rate
        assert loaded.pricing_context.exchange_rate_source is None


def _photon_scenario(rate, sales):
    from tests.test_price_source_safety import _policy

    scenario, _ = build_ihi_landed_cost_scenario(
        "PHOTON",
        exchange_rate=rate,
        policy=_policy(),
        dealer_values=resolve_ihi_dealer_values([]),
        sales_candidates=sales,
        price_book_candidates=[],
    )
    return scenario


def test_candidate_without_exchange_rate_is_not_adopted():
    sales = [_candidate("9680-BASE", 3339072.0, None)]
    draft = build_ihi_quote_draft("PHOTON", _photon_scenario(160.0, sales), sales)

    assert _line(draft).standard_sales_price_candidate_jpy is None
    assert any(STALE in item and "rate not recorded" in item for item in _line(draft).warnings)

    draft.exchange_rate = 165.0
    apply_exchange_rate(draft, 160, sales_candidates=sales)
    assert _line(draft).standard_sales_price_candidate_jpy is None


def test_candidate_with_missing_or_invalid_exchange_rate_is_not_adopted():
    payload = {
        "sales_price_candidate_id": "spc-missing",
        "spaceone_item_id": "so-9680",
        "manufacturer_sku": "9680-BASE",
        "raw_sales_price_jpy": 3339072.0,
        "source_reference": "PHOTON",
    }
    missing = SalesPriceCandidate.model_validate(payload)
    assert "exchange_rate" not in missing.model_dump(exclude_unset=True)
    for candidate in (missing, _candidate("9680-BASE", 1.0, 0.0), _candidate("9680-BASE", 1.0, -160.0), _candidate("9680-BASE", 1.0, float("nan"))):
        draft = build_ihi_quote_draft("PHOTON", _photon_scenario(160.0, [candidate]), [candidate])
        assert _line(draft).standard_sales_price_candidate_jpy is None
        assert any(STALE in item for item in _line(draft).warnings)


def test_candidate_with_the_quote_rate_is_adopted():
    sales = [_candidate("9680-BASE", 3339072.0, 160.0)]
    draft = build_ihi_quote_draft("PHOTON", _photon_scenario(160.0, sales), sales)

    assert _line(draft).standard_sales_price_candidate_jpy == 3339000.0
    assert not any(STALE in item for item in _line(draft).warnings)

    apply_exchange_rate(draft, 165, sales_candidates=[_candidate("9680-BASE", 3443418.0, 165.0)])
    assert _line(draft).standard_sales_price_candidate_jpy == 3443000.0


def test_scenario_display_keeps_rate_less_candidates_but_quotes_do_not(tmp_path, monkeypatch):
    scenario_only = [_candidate("9680-BASE", 3547764.0, None)]
    scenario = _photon_scenario(160.0, scenario_only)
    scenario_line = next(line for line in scenario.product_lines if line.sku == "9680-BASE")
    assert scenario_line.standard_sales_price_jpy == 3547764.0
    assert _line(build_ihi_quote_draft("PHOTON", scenario, scenario_only)).standard_sales_price_candidate_jpy is None

    _no_official_files(tmp_path, monkeypatch)
    at = _open_quote_page()
    at.session_state["sales_price_candidates"] = scenario_only
    at.run()
    at.button(key="ihi_photon_draft").click().run()

    assert not at.exception
    assert _line(at.session_state["quote_draft"]).standard_sales_price_candidate_jpy is None
