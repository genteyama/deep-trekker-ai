import json
from pathlib import Path

from streamlit.testing.v1 import AppTest

import ui.quote_control as quote_control
from agents.general_quote_entry import create_general_quote_draft
from agents.price_master import PriceMasterType, import_price_master
from tests.price_book_fixtures import build_workbook, quote_calc_formula_book
from tests.test_price_master_ui import _drop_stale_widgets, _open_quote_page, _texts
from tests.test_spectra_price_master import spectra_workbook
from ui.components.status import progress_text
from ui.navigation import PAGE_QUOTE_CONTROL, restore_navigation_state, stash_navigation_state
from ui.quote_steps import SESSION_QUOTE_STEP, build_header_summary, unresolved_required_lines, warning_count
from ui.warning_summary import summarize_draft_warnings
from ui.work_status import summarize_quote


def _activate():
    import_price_master(
        PriceMasterType.DT40,
        "DT40.xlsx",
        build_workbook(
            {
                "PHOTON": [
                    ["Part Number", "Description", "MSRP", "DT40", "Notes:"],
                    ["DT-100", "Deep Trekker Camera", 10000, 6000, None],
                    ["DT-200", "Deep Trekker Light", 2000, 1200, None],
                ]
            }
        ).getvalue(),
    )
    import_price_master(
        PriceMasterType.QUOTE_CALC,
        "QUOTE_CALC.xlsx",
        quote_calc_formula_book().getvalue(),
    )


def _line_id(at, index=0):
    return at.session_state["generic_quote_lines"][index]["id"]


def test_general_form_creates_a_saved_step_one_draft():
    _activate()
    at = _open_quote_page()
    line_id = _line_id(at)

    assert "一般見積を作成" in _texts(at)
    assert "SPECTRA 見積下書き" in _texts(at)
    at.text_input(key="generic_quote_customer").set_value("一般顧客")
    at.text_input(key="generic_quote_title").set_value("一般案件")
    at.text_input(key=f"generic_quote_sku_{line_id}").set_value("DT-100")
    at.text_input(key="generic_quote_international_shipping").set_value("100")
    at.text_input(key="generic_quote_domestic_shipping").set_value("0")
    at.button(key="generic_quote_create").click().run()

    assert not at.exception
    draft = at.session_state["quote_draft"]
    assert draft.customer == "一般顧客"
    assert draft.title == "一般案件"
    assert draft.configuration_name == "CUSTOM"
    assert draft.case_id is None
    assert draft.configuration_lines[0].manufacturer_sku == "DT-100"
    assert at.session_state[SESSION_QUOTE_STEP] == 1
    stored = at.session_state["quote_repository"].get_draft(draft.quote_draft_id)
    assert stored.draft.customer == "一般顧客"
    assert stored.draft.configuration_lines[0].manufacturer_sku == "DT-100"


def test_navigation_does_not_create_a_draft_and_restores_pre_draft_input():
    at = _open_quote_page()
    line_id = _line_id(at)
    at.text_input(key="generic_quote_customer").set_value("保管顧客")
    at.text_input(key="generic_quote_title").set_value("保管案件")
    at.text_input(key=f"generic_quote_sku_{line_id}").set_value("DT-100")
    at.number_input(key=f"generic_quote_qty_{line_id}").set_value(3)
    at.text_input(key="generic_quote_international_shipping").set_value("12")
    at.text_input(key="generic_quote_domestic_shipping").set_value("34")
    at.button(key="sidebar_nav_home").click().run()
    _drop_stale_widgets(at)

    assert "quote_draft" not in at.session_state or at.session_state["quote_draft"] is None
    assert at.session_state["quote_repository"].list_recent_drafts() == []

    at.button(key="sidebar_nav_quote").click().run()
    assert "quote_draft" not in at.session_state or at.session_state["quote_draft"] is None
    assert at.text_input(key="generic_quote_customer").value == "保管顧客"
    assert at.text_input(key="generic_quote_title").value == "保管案件"
    assert at.text_input(key=f"generic_quote_sku_{line_id}").value == "DT-100"
    assert at.number_input(key=f"generic_quote_qty_{line_id}").value == 3
    assert at.text_input(key="generic_quote_international_shipping").value == "12"
    assert at.text_input(key="generic_quote_domestic_shipping").value == "34"


def test_general_pre_draft_stash_restores_lines_when_widget_keys_are_gone():
    line = {"id": "line-1", "sku": "DT-100", "quantity": 2}
    session = {
        "generic_quote_customer": "保管顧客",
        "generic_quote_title": "保管案件",
        "generic_quote_lines": [line],
        "generic_quote_international_shipping": "12",
        "generic_quote_domestic_shipping": "34",
    }
    stash_navigation_state(session, PAGE_QUOTE_CONTROL)
    for key in (
        "generic_quote_customer",
        "generic_quote_title",
        "generic_quote_lines",
        "generic_quote_international_shipping",
        "generic_quote_domestic_shipping",
    ):
        session.pop(key, None)

    restore_navigation_state(session, PAGE_QUOTE_CONTROL)

    assert session["generic_quote_customer"] == "保管顧客"
    assert session["generic_quote_title"] == "保管案件"
    assert session["generic_quote_lines"] == [line]
    assert session["generic_quote_international_shipping"] == "12"
    assert session["generic_quote_domestic_shipping"] == "34"


def test_removing_a_line_does_not_move_another_sku():
    at = _open_quote_page()
    first = _line_id(at)
    at.button(key="generic_quote_add_line").click().run()
    second = _line_id(at, 1)
    at.text_input(key=f"generic_quote_sku_{first}").set_value("DT-100")
    at.text_input(key=f"generic_quote_sku_{second}").set_value("DT-200")
    at.button(key=f"generic_quote_remove_{first}").click().run()

    remaining = at.session_state["generic_quote_lines"]
    assert [item["id"] for item in remaining] == [second]
    assert remaining[0]["sku"] == "DT-200"
    assert at.text_input(key=f"generic_quote_sku_{second}").value == "DT-200"


def test_unknown_sku_shows_the_entered_sku_and_does_not_save():
    _activate()
    at = _open_quote_page()
    line_id = _line_id(at)
    at.text_input(key="generic_quote_customer").set_value("一般顧客")
    at.text_input(key=f"generic_quote_sku_{line_id}").set_value("DT-404")
    at.button(key="generic_quote_create").click().run()

    assert "quote_draft" not in at.session_state or at.session_state["quote_draft"] is None
    assert at.session_state["quote_repository"].list_recent_drafts() == []
    errors = " ".join(item.value for item in at.error)
    assert "DT-404" in errors
    assert "DT-100" not in errors


def test_ihi_samples_stay_collapsed_and_spectra_entry_stays_separate(monkeypatch):
    import_price_master(
        PriceMasterType.SPECTRA_GOLD,
        "SPECTRA_GOLD.xlsx",
        spectra_workbook(first_msrp=202500, first_gold=141750).getvalue(),
    )
    import_price_master(
        PriceMasterType.QUOTE_CALC,
        "QUOTE_CALC.xlsx",
        quote_calc_formula_book().getvalue(),
    )

    def fail_if_all_manufacturer_books_are_loaded():
        raise AssertionError("SPECTRA entry must not load DT40/PT30")

    monkeypatch.setattr(quote_control, "active_price_books", fail_if_all_manufacturer_books_are_loaded)
    at = _open_quote_page()
    sample = next(item for item in at.expander if item.label == "検証用・固定サンプル")
    assert sample.proto.expanded is False
    assert any(item.key == "ihi_photon_draft" for item in at.button)
    assert any(item.key == "ihi_mag_draft" for item in at.button)

    at.text_input(key="spectra_quote_customer").set_value("UI Customer")
    at.text_input(key="spectra_quote_sku").set_value("SPECTRA0001")
    at.text_input(key="spectra_quote_international_shipping").set_value("2500")
    at.text_input(key="spectra_quote_domestic_shipping").set_value("0")
    at.button(key="spectra_quote_create").click().run()

    draft = at.session_state["quote_draft"]
    assert draft.configuration_name == "SPECTRA"
    assert draft.configuration_lines[0].manufacturer_sku == "SPECTRA0001"
    assert draft.case_id is None


HEADER_REVIEW_DRAFT = None


def _render_header_review_draft():
    import json
    from pathlib import Path

    from tests.test_quote_general_ui import HEADER_REVIEW_DRAFT
    from ui.components.quote_header import render_quote_header

    page = json.loads(Path("locales/ja.json").read_text(encoding="utf-8"))["pages"]["quote_control"]
    render_quote_header(page, HEADER_REVIEW_DRAFT, None)


def test_general_quote_header_uses_one_review_count():
    _activate()
    draft = create_general_quote_draft(
        customer="一般顧客",
        title="一般案件",
        lines=[{"sku": "DT-100", "quantity": 1}],
        exchange_rate=160,
        international_shipping_usd=None,
        domestic_shipping_jpy=None,
        sales_candidates=[],
    )
    work = summarize_quote(draft)
    classified = summarize_draft_warnings(draft)
    kinds = dict(classified["lines"])
    page = json.loads((Path("locales/ja.json")).read_text(encoding="utf-8"))["pages"]["quote_control"]
    workspace = page["workspace"]

    assert work.review_required == 7
    assert kinds["international_shipping"] == 1
    assert kinds["domestic_shipping"] == 1
    assert kinds["lead_time"] == 1
    assert work.review_required == classified["count"]
    assert draft.lead_time_text in (None, "")
    with_lead_time = draft.model_copy(update={"lead_time_text": "4週間"})
    assert summarize_quote(with_lead_time).review_required == 6
    raw_count = (
        len(draft.warnings)
        + sum(len(line.warnings) for line in draft.configuration_lines)
        + len(unresolved_required_lines(draft))
    )
    assert warning_count(draft) == raw_count
    assert build_header_summary(draft)["warning_count"] == raw_count
    assert warning_count(draft) != work.review_required

    global HEADER_REVIEW_DRAFT
    HEADER_REVIEW_DRAFT = draft
    at = AppTest.from_function(_render_header_review_draft).run()
    html = " ".join(item.value for item in at.markdown)
    progress = progress_text(work, workspace)
    card = f"<div class='label'>要確認</div><div class='value'>{work.review_required}件</div>"

    assert progress in html
    assert "要確認：7件" in progress
    assert card in html
