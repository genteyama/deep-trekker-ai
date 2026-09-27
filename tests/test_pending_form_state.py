from datetime import date

from agents.quote_builder import apply_final_price, apply_shipping_final_price, apply_tax_rate, refresh_quote_draft
from agents.quote_dates import apply_date_widget_defaults, date_widget_keys
from models import FinalPriceStatus
from repositories.sqlite_quote_repository import SqliteQuoteRepository
from tests.test_quote_approval import _approve, _ready_photon
from tests.test_quote_builder import _photon_draft
from ui.quote_persistence import (
    PENDING_FORM_KEY,
    apply_ui_state,
    customer_description_widget_key,
    manual_price_widget_key,
    maybe_autosave,
    restore_pending_form_widgets,
    save_draft_now,
)
from ui.quote_steps import SESSION_QUOTE_STEP, persist_review_key


def _base_line(draft):
    return next(line for line in draft.configuration_lines if line.manufacturer_sku == "9680-BASE")


def _camera_line(draft):
    return next(line for line in draft.configuration_lines if line.manufacturer_sku == "8459")


def _product_customer(draft):
    return next(line for line in draft.customer_lines if line.line_kind == "PRODUCT")


def _shipping_amount(draft):
    shipping = next(line for line in draft.customer_lines if line.line_kind == "SHIPPING")
    return shipping.amount_jpy


def test_pending_final_price_saves_and_resumes_without_applying():
    draft = _photon_draft()
    base = _base_line(draft)
    camera = _camera_line(draft)
    official_base = base.final_sales_price_jpy
    official_camera = camera.final_sales_price_jpy
    session = {
        SESSION_QUOTE_STEP: 2,
        manual_price_widget_key(base.line_id): "3540000",
        manual_price_widget_key(camera.line_id): "160000",
    }
    repo = SqliteQuoteRepository()
    save_draft_now(repo, draft, session)
    loaded = repo.get_draft(draft.quote_draft_id, draft.quote_version)

    assert loaded.draft.configuration_lines[0].final_sales_price_jpy == official_base
    assert next(line for line in loaded.draft.configuration_lines if line.manufacturer_sku == "8459").final_sales_price_jpy == official_camera
    assert loaded.ui_state["pending_final_prices"][base.line_id] == "3540000"
    assert loaded.ui_state["pending_final_prices"][camera.line_id] == "160000"
    assert "9680-BASE" not in loaded.ui_state["pending_final_prices"]
    assert "8459" not in loaded.ui_state["pending_final_prices"]

    resumed = {}
    apply_ui_state(resumed, loaded.draft, loaded.ui_state, init_dates=apply_date_widget_defaults)
    assert resumed[manual_price_widget_key(base.line_id)] == "3540000"
    assert resumed[manual_price_widget_key(camera.line_id)] == "160000"
    assert loaded.draft.total_jpy == draft.total_jpy


def test_pending_shipping_and_tax_save_and_resume_without_applying():
    draft = _photon_draft()
    official_shipping = _shipping_amount(draft)
    official_tax = draft.tax_rate
    session = {
        SESSION_QUOTE_STEP: 3,
        "input_draft_shipping_price": "870000",
        "input_draft_tax_rate": "0.10",
    }
    repo = SqliteQuoteRepository()
    save_draft_now(repo, draft, session)
    loaded = repo.get_draft(draft.quote_draft_id)

    assert _shipping_amount(loaded.draft) == official_shipping
    assert loaded.draft.tax_rate == official_tax
    assert loaded.ui_state["pending_shipping_customer_price"] == "870000"
    assert loaded.ui_state["pending_tax_rate"] == "0.10"

    resumed = {}
    apply_ui_state(resumed, loaded.draft, loaded.ui_state, init_dates=apply_date_widget_defaults)
    assert resumed["input_draft_shipping_price"] == "870000"
    assert resumed["input_draft_tax_rate"] == "0.10"


def test_pending_customer_description_and_remarks_save_and_resume():
    draft = _photon_draft()
    customer = _product_customer(draft)
    official_description = customer.description
    official_remarks = list(draft.remarks)
    remark = draft.remark_candidates[0].text
    session = {
        SESSION_QUOTE_STEP: 4,
        customer_description_widget_key(customer.customer_quote_line_id): "編集中の顧客向け説明",
        persist_review_key("input_selected_remarks"): [remark],
        "input_selected_remarks": [remark],
    }
    repo = SqliteQuoteRepository()
    save_draft_now(repo, draft, session)
    loaded = repo.get_draft(draft.quote_draft_id)
    loaded_customer = next(
        line
        for line in loaded.draft.customer_lines
        if line.customer_quote_line_id == customer.customer_quote_line_id
    )

    assert loaded_customer.description == official_description
    assert list(loaded.draft.remarks) == official_remarks
    assert loaded.ui_state["pending_customer_descriptions"][customer.customer_quote_line_id] == "編集中の顧客向け説明"
    assert loaded.ui_state["selected_remarks"] == [remark]

    resumed = {}
    apply_ui_state(resumed, loaded.draft, loaded.ui_state, init_dates=apply_date_widget_defaults)
    assert resumed[customer_description_widget_key(customer.customer_quote_line_id)] == "編集中の顧客向け説明"
    assert resumed["input_selected_remarks"] == [remark]


def test_pending_dates_and_auto_valid_until_save_and_resume():
    draft = _photon_draft()
    draft.issue_date = "2026-09-27"
    draft.valid_until = "2026-10-27"
    draft.auto_valid_until = True
    keys = date_widget_keys(draft.quote_draft_id)
    session = {
        SESSION_QUOTE_STEP: 4,
        keys["issue"]: date(2026, 9, 27),
        keys["valid"]: date(2026, 10, 27),
        keys["auto"]: True,
    }
    repo = SqliteQuoteRepository()
    save_draft_now(repo, draft, session)
    loaded = repo.get_draft(draft.quote_draft_id)

    assert loaded.ui_state["issue_date"] == "2026-09-27"
    assert loaded.ui_state["valid_until"] == "2026-10-27"
    assert loaded.ui_state["auto_valid_until"] is True

    resumed = {}
    apply_ui_state(resumed, loaded.draft, loaded.ui_state, init_dates=apply_date_widget_defaults)
    assert resumed[keys["issue"]] == date(2026, 9, 27)
    assert resumed[keys["valid"]] == date(2026, 10, 27)
    assert resumed[keys["auto"]] is True


def test_pending_values_do_not_mutate_quote_draft_on_save():
    draft = _photon_draft()
    before = draft.model_dump(mode="json")
    session = {
        SESSION_QUOTE_STEP: 2,
        manual_price_widget_key(_base_line(draft).line_id): "9999999",
        "input_draft_shipping_price": "1",
        "input_draft_tax_rate": "0.99",
    }
    repo = SqliteQuoteRepository()
    save_draft_now(repo, draft, session)
    loaded = repo.get_draft(draft.quote_draft_id)

    assert loaded.draft.model_dump(mode="json") == before
    assert "9999999" not in str(loaded.draft.model_dump(mode="json"))


def test_apply_updates_quote_draft_and_clears_pending():
    draft = _photon_draft()
    base = _base_line(draft)
    session = {
        SESSION_QUOTE_STEP: 2,
        manual_price_widget_key(base.line_id): "3540000",
        "input_draft_shipping_price": "870000",
        "input_draft_tax_rate": "0.10",
        PENDING_FORM_KEY: {
            "pending_final_prices": {base.line_id: "3540000"},
            "pending_shipping_customer_price": "870000",
            "pending_tax_rate": "0.10",
        },
    }
    apply_final_price(draft, base.line_id, FinalPriceStatus.MANUAL_OVERRIDE, amount_jpy=3540000, reason="test")
    apply_shipping_final_price(draft, 870000)
    apply_tax_rate(draft, 0.10)
    from ui.quote_persistence import clear_pending_final_price, clear_pending_shipping, clear_pending_tax

    clear_pending_final_price(session, base)
    clear_pending_shipping(session)
    clear_pending_tax(session)

    assert _base_line(draft).final_sales_price_jpy == 3540000
    assert _shipping_amount(draft) == 870000
    assert draft.tax_rate == 0.10
    assert base.line_id not in (session[PENDING_FORM_KEY].get("pending_final_prices") or {})
    assert session[PENDING_FORM_KEY]["pending_shipping_customer_price"] == ""
    assert session[PENDING_FORM_KEY]["pending_tax_rate"] == ""


def test_approval_snapshot_ignores_unapplied_pending_values():
    draft = _ready_photon()
    official_total = draft.total_jpy
    official_margin = draft.economics_result.gross_margin_rate
    base = _base_line(draft)
    session = {
        SESSION_QUOTE_STEP: 4,
        manual_price_widget_key(base.line_id): "1",
        "input_draft_shipping_price": "1",
        "input_draft_tax_rate": "0.50",
    }
    repo = SqliteQuoteRepository()
    save_draft_now(repo, draft, session)
    loaded = repo.get_draft(draft.quote_draft_id)
    _, snapshot = _approve(loaded.draft)
    repo.save_snapshot(snapshot)
    stored = repo.get_snapshot(snapshot.approved_quote_snapshot_id)
    payload = stored.model_dump(mode="json")

    assert stored.total_jpy == 7876000 == official_total
    assert abs(stored.gross_margin_rate - 0.29598) < 0.00001
    assert stored.gross_margin_rate == official_margin
    assert "pending_final_prices" not in payload
    assert "ui_state" not in payload
    assert "870000" not in str(payload) or stored.total_jpy == 7876000
    assert _base_line(loaded.draft).final_sales_price_jpy == 3540000
    assert all(line.final_sales_price_jpy != 1 for line in stored.configuration_snapshot)


def test_sqlite_restore_after_cleared_session_and_reopen():
    path = None
    draft = _photon_draft()
    base = _base_line(draft)
    customer = _product_customer(draft)
    keys = date_widget_keys(draft.quote_draft_id)
    draft.issue_date = "2026-09-27"
    draft.valid_until = "2026-10-27"
    draft.auto_valid_until = False
    session = {
        SESSION_QUOTE_STEP: 3,
        manual_price_widget_key(base.line_id): "3540000",
        "input_draft_shipping_price": "870000",
        "input_draft_tax_rate": "0.10",
        customer_description_widget_key(customer.customer_quote_line_id): "途中の説明",
        keys["issue"]: date(2026, 9, 27),
        keys["valid"]: date(2026, 10, 27),
        keys["auto"]: False,
    }
    first = SqliteQuoteRepository()
    save_draft_now(first, draft, session)
    path = first.path
    first.close()

    second = SqliteQuoteRepository(path)
    loaded = second.get_draft(draft.quote_draft_id)
    resumed = {}
    apply_ui_state(resumed, loaded.draft, loaded.ui_state, init_dates=apply_date_widget_defaults)
    restore_pending_form_widgets(resumed, loaded.draft)

    assert loaded.draft.model_dump(mode="json") == draft.model_dump(mode="json")
    assert resumed[manual_price_widget_key(base.line_id)] == "3540000"
    assert resumed["input_draft_shipping_price"] == "870000"
    assert resumed["input_draft_tax_rate"] == "0.10"
    assert resumed[customer_description_widget_key(customer.customer_quote_line_id)] == "途中の説明"
    assert resumed[keys["issue"]] == date(2026, 9, 27)
    assert resumed[keys["auto"]] is False


def test_restore_pending_does_not_overwrite_existing_widget_keys():
    draft = _photon_draft()
    base = _base_line(draft)
    key = manual_price_widget_key(base.line_id)
    session = {
        PENDING_FORM_KEY: {"pending_final_prices": {base.line_id: "3540000"}},
        key: "already-set",
    }
    restore_pending_form_widgets(session, draft)
    assert session[key] == "already-set"


def test_unmounted_empty_widgets_do_not_wipe_stored_pending():
    draft = _photon_draft()
    session = {
        SESSION_QUOTE_STEP: 3,
        "input_draft_tax_rate": "0.10",
        "input_draft_shipping_price": "870000",
    }
    repo = SqliteQuoteRepository()
    save_draft_now(repo, draft, session)
    session[SESSION_QUOTE_STEP] = 4
    session["input_draft_tax_rate"] = ""
    session["input_draft_shipping_price"] = ""
    maybe_autosave(repo, draft, session)
    loaded = repo.get_draft(draft.quote_draft_id)

    assert loaded.ui_state["pending_tax_rate"] == "0.10"
    assert loaded.ui_state["pending_shipping_customer_price"] == "870000"


def test_autosave_skips_when_pending_ui_state_is_unchanged():
    draft = _photon_draft()
    session = {
        SESSION_QUOTE_STEP: 2,
        manual_price_widget_key(_base_line(draft).line_id): "3540000",
    }
    repo = SqliteQuoteRepository()
    first = maybe_autosave(repo, draft, session)
    second = maybe_autosave(repo, draft, session)
    session[manual_price_widget_key(_base_line(draft).line_id)] = "3540001"
    third = maybe_autosave(repo, draft, session)

    assert first.saved is True
    assert second.skipped is True
    assert second.updated_at == first.updated_at
    assert third.saved is True
    assert third.content_hash != first.content_hash


def test_applied_description_updates_draft_only_after_refresh():
    draft = _photon_draft()
    customer = _product_customer(draft)
    config = next(line for line in draft.configuration_lines if line.line_id in customer.source_configuration_line_ids)
    official = customer.description
    session = {customer_description_widget_key(customer.customer_quote_line_id): "未反映の説明"}
    repo = SqliteQuoteRepository()
    save_draft_now(repo, draft, session)
    loaded = repo.get_draft(draft.quote_draft_id)
    loaded_customer = next(
        line for line in loaded.draft.customer_lines if line.customer_quote_line_id == customer.customer_quote_line_id
    )
    assert loaded_customer.description == official

    config.customer_description = "反映した説明"
    refresh_quote_draft(draft)
    updated = next(line for line in draft.customer_lines if line.customer_quote_line_id == customer.customer_quote_line_id)
    assert updated.description == "反映した説明"


def test_pending_ui_state_does_not_change_excel_or_pdf_export(tmp_path):
    from agents.formal_quote_document import build_formal_quote_document
    from agents.quote_export import export_spaceone_quote_excel
    from agents.quote_pdf import render_formal_quote_pdf
    from models import ExportPurpose

    draft = _ready_photon()
    session = {
        SESSION_QUOTE_STEP: 5,
        manual_price_widget_key(_base_line(draft).line_id): "1",
        "input_draft_shipping_price": "1",
        "input_draft_tax_rate": "0.50",
    }
    repo = SqliteQuoteRepository()
    save_draft_now(repo, draft, session)
    loaded = repo.get_draft(draft.quote_draft_id)
    _, snapshot = _approve(loaded.draft)
    document = build_formal_quote_document(snapshot, official_quote_number="8195")
    _, excel_path = export_spaceone_quote_excel(
        snapshot,
        output_dir=tmp_path,
        official_quote_number="8195",
        generated_by="弦",
        purpose=ExportPurpose.FORMAL,
    )
    pdf_path = tmp_path / "pending.pdf"
    render_formal_quote_pdf(document, pdf_path)

    assert snapshot.total_jpy == 7876000
    assert document.total == 7876000
    assert excel_path.exists()
    assert pdf_path.exists() and pdf_path.stat().st_size > 0


def test_photon_totals_stay_unchanged_with_pending_ui_state():
    draft = _ready_photon()
    session = {
        SESSION_QUOTE_STEP: 4,
        manual_price_widget_key(_base_line(draft).line_id): "1",
        "input_draft_shipping_price": "1",
    }
    repo = SqliteQuoteRepository()
    save_draft_now(repo, draft, session)
    loaded = repo.get_draft(draft.quote_draft_id)
    _, snapshot = _approve(loaded.draft)

    assert loaded.draft.total_jpy == 7876000
    assert abs(loaded.draft.economics_result.gross_margin_rate - 0.29598) < 0.00001
    assert snapshot.total_jpy == 7876000
    assert abs(snapshot.gross_margin_rate - 0.29598) < 0.00001


def _duplicate_sku_line(draft, sku: str):
    original = next(line for line in draft.configuration_lines if line.manufacturer_sku == sku)
    clone = original.model_copy(deep=True)
    clone.line_id = f"{original.line_id}-dup"
    draft.configuration_lines.append(clone)
    return original, clone


def test_pending_final_prices_use_line_id_and_never_sku_on_new_save():
    draft = _photon_draft()
    base = _base_line(draft)
    camera = _camera_line(draft)
    session = {
        SESSION_QUOTE_STEP: 2,
        manual_price_widget_key(base.line_id): "3540000",
        manual_price_widget_key(camera.line_id): "160000",
    }
    repo = SqliteQuoteRepository()
    save_draft_now(repo, draft, session)
    loaded = repo.get_draft(draft.quote_draft_id)
    keys = set(loaded.ui_state["pending_final_prices"])

    assert keys == {base.line_id, camera.line_id}
    assert "9680-BASE" not in keys
    assert "8459" not in keys


def test_duplicate_sku_pending_prices_do_not_collide():
    draft = _photon_draft()
    first, second = _duplicate_sku_line(draft, "5608")
    session = {
        SESSION_QUOTE_STEP: 2,
        manual_price_widget_key(first.line_id): "2220000",
        manual_price_widget_key(second.line_id): "2330000",
    }
    repo = SqliteQuoteRepository()
    save_draft_now(repo, draft, session)
    loaded = repo.get_draft(draft.quote_draft_id)
    prices = loaded.ui_state["pending_final_prices"]

    assert prices[first.line_id] == "2220000"
    assert prices[second.line_id] == "2330000"
    assert "5608" not in prices


def test_legacy_sku_key_migrates_only_when_unique():
    from ui.quote_persistence import migrate_pending_final_prices

    draft = _photon_draft()
    base = _base_line(draft)
    migrated, reviews = migrate_pending_final_prices({"9680-BASE": "3540000", base.line_id: "3540000"}, draft)
    repo = SqliteQuoteRepository()
    repo.save_draft(draft, {"step": 2, "pending_final_prices": {"9680-BASE": "3540000"}})
    loaded = repo.get_draft(draft.quote_draft_id)
    resumed = {}
    apply_ui_state(resumed, loaded.draft, loaded.ui_state, init_dates=apply_date_widget_defaults)

    assert migrated == {base.line_id: "3540000"}
    assert reviews == []
    assert resumed[PENDING_FORM_KEY]["pending_final_prices"] == {base.line_id: "3540000"}
    assert "9680-BASE" not in resumed[PENDING_FORM_KEY]["pending_final_prices"]
    assert resumed[manual_price_widget_key(base.line_id)] == "3540000"


def test_legacy_ambiguous_sku_key_is_not_migrated():
    from ui.quote_persistence import AMBIGUOUS_SKU_REASON, migrate_pending_final_prices

    draft = _photon_draft()
    first, second = _duplicate_sku_line(draft, "5608")
    migrated, reviews = migrate_pending_final_prices({"5608": "2220000"}, draft)
    resumed = {}
    apply_ui_state(
        resumed,
        draft,
        {"step": 2, "pending_final_prices": {"5608": "2220000"}},
        init_dates=apply_date_widget_defaults,
    )

    assert migrated == {}
    assert len(reviews) == 1
    assert reviews[0]["sku"] == "5608"
    assert reviews[0]["amount"] == "2220000"
    assert reviews[0]["reason"] == AMBIGUOUS_SKU_REASON
    assert set(reviews[0]["candidate_line_ids"]) == {first.line_id, second.line_id}
    assert resumed[PENDING_FORM_KEY]["pending_final_prices"] == {}
    assert resumed[PENDING_FORM_KEY]["pending_final_price_reviews"][0]["sku"] == "5608"
    assert manual_price_widget_key(first.line_id) not in resumed
    assert manual_price_widget_key(second.line_id) not in resumed


def test_export_inputs_save_and_resume_without_changing_snapshot():
    draft = _ready_photon()
    official_total = draft.total_jpy
    session = {
        SESSION_QUOTE_STEP: 5,
        "input_official_quote_number": "8195",
        "input_export_generated_by": "Gen Oteyama",
    }
    repo = SqliteQuoteRepository()
    save_draft_now(repo, draft, session)
    loaded = repo.get_draft(draft.quote_draft_id)
    _, snapshot = _approve(loaded.draft)
    repo.save_snapshot(snapshot)
    stored = repo.get_snapshot(snapshot.approved_quote_snapshot_id)
    resumed = {}
    apply_ui_state(resumed, loaded.draft, loaded.ui_state, init_dates=apply_date_widget_defaults)

    assert loaded.ui_state["pending_official_quote_number"] == "8195"
    assert loaded.ui_state["pending_generated_by"] == "Gen Oteyama"
    assert resumed["input_official_quote_number"] == "8195"
    assert resumed["input_export_generated_by"] == "Gen Oteyama"
    assert stored.official_quote_number is None
    assert stored.total_jpy == 7876000 == official_total
    assert "Gen Oteyama" not in str(stored.model_dump(mode="json"))
