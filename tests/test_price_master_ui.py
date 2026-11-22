from pathlib import Path

import pytest
import streamlit
from streamlit.testing.v1 import AppTest

from agents.price_master import import_price_master
from models import PriceMasterImportOutcome, PriceMasterImportStatus, PriceMasterType, PriceSourceType
from repositories.sqlite_quote_repository import SqliteQuoteRepository
from tests.price_book_fixtures import missing_columns_price_book, official_ihi_sku_snapshot_book
from tests.test_price_master_consumers import _line, _photon_dt40_book
from ui.price_master import format_imported_at, outcome_message

APP_PATH = Path(__file__).resolve().parents[1] / "app.py"
LABELS = {
    "labels": {"DT40": "DT40（Deep Trekker 価格表）"},
    "outcomes": {
        "ACTIVATED": "{label}を取り込み、有効にしました（{file}）。",
        "ALREADY_ACTIVE": "同じ内容の{label}がすでに有効です。",
        "REACTIVATED": "{label}（{date}取込）を有効に戻しました。",
        "NOT_XLSX": "{label}はExcel（.xlsx）ファイルを選択してください。",
        "VALIDATION_FAILED": "{label}として読み込めませんでした。ファイル内容をご確認ください。",
        "STORAGE_FAILED": "{label}の保存に失敗しました。",
    },
}


class _Upload:
    def __init__(self, name, data):
        self.name = name
        self._data = data

    def getvalue(self):
        return self._data


@pytest.fixture
def uploads(monkeypatch):
    """Stand-in for the browser file picker: returns a chosen file for one uploader key."""
    chosen = {}
    original = streamlit.file_uploader

    def fake_file_uploader(label, *args, key=None, **kwargs):
        if key in chosen:
            return chosen[key]
        return original(label, *args, key=key, **kwargs)

    monkeypatch.setattr(streamlit, "file_uploader", fake_file_uploader)
    return chosen


def _open_quote_page() -> AppTest:
    at = AppTest.from_file(str(APP_PATH)).run()
    at.session_state["quote_ui_mode"] = "legacy"  # legacy 5-step workspace
    at.button(key="sidebar_nav_quote").click().run()
    assert not at.exception
    return at


def _drop_stale_widgets(at) -> None:
    """Drop widgets left in the AppTest tree after a navigation rerun."""

    def walk(block) -> None:
        children = getattr(block, "children", None)
        if not children:
            return
        stale = []
        for idx, child in list(children.items()):
            lookup = getattr(child, "key", None) or getattr(child, "id", None)
            if lookup:
                try:
                    at.session_state[lookup]
                except KeyError:
                    stale.append(idx)
                    continue
            walk(child)
        for idx in stale:
            del children[idx]

    walk(at._tree)


def _open_price_master_page() -> AppTest:
    at = AppTest.from_file(str(APP_PATH)).run()
    at.button(key="sidebar_admin_price_master").click().run()
    assert not at.exception
    _drop_stale_widgets(at)
    return at


def _texts(at):
    return " ".join(
        [item.value for item in at.markdown]
        + [item.value for item in at.caption]
        + [item.value for item in at.success]
        + [item.value for item in at.error]
        + [item.value for item in at.info]
        + [item.value for item in at.warning]
    )


def test_quote_page_hides_price_master_administration():
    at = _open_quote_page()

    assert not any(item.label == "価格マスター管理" for item in at.expander)
    assert not any(item.key == "price_master_import_DT40" for item in at.button)
    assert any(item.key == "ihi_photon_draft" for item in at.button)
    assert "最近の下書き" in _texts(at)


def test_price_master_page_shows_unset_master_status():
    at = _open_price_master_page()

    texts = _texts(at)
    assert "価格マスター状態" in texts
    assert "DT40：未設定（取り込みが必要です）" in texts
    assert "SpaceOne価格マスター：未設定（取り込みが必要です）" in texts
    assert any(item.label == "価格マスター管理" for item in at.expander)
    assert any(item.key == "price_master_import_DT40" for item in at.button)
    assert any(item.key == "price_master_import_QUOTE_CALC" for item in at.button)


def test_import_without_choosing_a_file_asks_for_one():
    at = _open_price_master_page()
    at.button(key="price_master_import_DT40").click().run()

    assert "ファイルを選択してください。" in _texts(at)


def test_upload_import_activate_then_quote_uses_it_and_existing_drafts_stay(uploads):
    uploads["price_master_upload_DT40"] = _Upload("9月 DT40.xlsx", _photon_dt40_book(10434.6).getvalue())
    at = _open_price_master_page()
    at.button(key="price_master_import_DT40").click().run()

    assert not at.exception
    texts = _texts(at)
    assert "DT40（Deep Trekker 価格表）を取り込み、有効にしました（9月 DT40.xlsx）" in texts
    assert "DT40：有効 /" in texts and "取込" in texts

    at.session_state["quote_ui_mode"] = "legacy"  # legacy 5-step workspace
    at.button(key="sidebar_nav_quote").click().run()
    _drop_stale_widgets(at)
    at.button(key="ihi_photon_draft").click().run()
    first = at.session_state["quote_draft"]
    assert _line(first).manufacturer_price_snapshot.price_source_type == PriceSourceType.OFFICIAL_PRICE_BOOK
    assert _line(first).dealer_price_usd == 10434.6
    stored_before = SqliteQuoteRepository().get_draft(first.quote_draft_id).draft.model_dump(mode="json")

    uploads["price_master_upload_DT40"] = _Upload("10月 DT40.xlsx", _photon_dt40_book(11000.0).getvalue())
    at.button(key="sidebar_admin_price_master").click().run()
    _drop_stale_widgets(at)
    at.button(key="price_master_import_DT40").click().run()
    assert "（10月 DT40.xlsx）" in _texts(at)
    assert SqliteQuoteRepository().get_draft(first.quote_draft_id).draft.model_dump(mode="json") == stored_before
    assert _line(at.session_state["quote_draft"]).dealer_price_usd == 10434.6

    at.session_state["quote_ui_mode"] = "legacy"  # legacy 5-step workspace
    at.button(key="sidebar_nav_quote").click().run()
    _drop_stale_widgets(at)
    at.button(key="ihi_photon_draft").click().run()
    assert _line(at.session_state["quote_draft"]).dealer_price_usd == 11000.0


def test_invalid_upload_shows_a_plain_message_and_keeps_the_active_master(uploads):
    good = import_price_master(PriceMasterType.DT40, "good.xlsx", official_ihi_sku_snapshot_book().getvalue()).record
    uploads["price_master_upload_DT40"] = _Upload("wrong.xlsx", missing_columns_price_book().getvalue())
    at = _open_price_master_page()
    at.button(key="price_master_import_DT40").click().run()

    assert not at.exception
    errors = " ".join(item.value for item in at.error)
    assert "DT40（Deep Trekker 価格表）として読み込めませんでした。ファイル内容をご確認ください。" in errors
    assert "Traceback" not in _texts(at)
    from agents.price_master import get_active_master

    assert get_active_master(PriceMasterType.DT40).record.import_id == good.import_id


def test_outcome_messages_are_plain_japanese():
    rejected = PriceMasterImportOutcome(
        status=PriceMasterImportStatus.REJECTED, master_type=PriceMasterType.DT40, reason_code="NOT_XLSX"
    )
    assert outcome_message(LABELS, rejected) == ("error", "DT40（Deep Trekker 価格表）はExcel（.xlsx）ファイルを選択してください。")
    record = import_price_master(PriceMasterType.DT40, "a.xlsx", official_ihi_sku_snapshot_book().getvalue()).record
    same = PriceMasterImportOutcome(status=PriceMasterImportStatus.ALREADY_ACTIVE, master_type=PriceMasterType.DT40, record=record)
    assert outcome_message(LABELS, same)[0] == "info"


def test_imported_at_is_shown_in_tokyo_time():
    assert format_imported_at("2026-10-06T15:30:00+00:00") == "2026-10-07 00:30"
    assert format_imported_at("2026-10-06T15:30:00+00:00", date_only=True) == "2026-10-07"
    assert format_imported_at(None) == "-"


def _shipping_rate_key(at, shipping_type: str) -> str:
    return next(item.key for item in at.number_input if item.key.startswith(f"shipping_rate_{shipping_type}_"))


def test_shipping_reference_admin_shows_three_types_and_updates_with_history():
    from models import RecordStatus, ShippingType
    from repositories.shipping_rule_repository import ShippingRuleRepository

    at = _open_price_master_page()
    assert any(item.value == "国際輸送費（参考）管理" for item in at.header)
    for shipping_type in ("LARGE_BOX", "SMALL_BOX", "PIPE_TREKKER"):
        assert any(item.key == f"shipping_save_{shipping_type}" for item in at.button)
        assert at.button(key=f"shipping_save_{shipping_type}").label == "国際輸送費を更新"
    tables = " ".join(str(table.value.to_dict()) for table in at.table)
    assert "1個口あたり" in tables
    assert "PT本体発注時の基本一式" in tables
    assert "$2,922.15" in tables
    assert "2026-10-23" in tables

    at.button(key="shipping_save_LARGE_BOX").click().run()
    assert "変更はありません" in _texts(at)
    assert len(ShippingRuleRepository().list_history(ShippingType.LARGE_BOX)) == 1

    at.number_input(key=_shipping_rate_key(at, "LARGE_BOX")).set_value(3100.0).run()
    at.button(key="shipping_save_LARGE_BOX").click().run()
    _drop_stale_widgets(at)
    assert not at.exception
    assert "Large Box Shipping Globally を $3,100.00 に更新しました。" in _texts(at)
    history = ShippingRuleRepository().list_history(ShippingType.LARGE_BOX)
    assert [item.rule.status for item in history] == [RecordStatus.APPROVED, RecordStatus.SUPERSEDED]
    assert ShippingRuleRepository().get_active_standard_global(ShippingType.SMALL_BOX).rule.rate_usd == 1356.0


def test_shipping_reference_admin_rejects_zero_without_saving():
    from models import ShippingType
    from repositories.shipping_rule_repository import ShippingRuleRepository

    at = _open_price_master_page()
    at.number_input(key=_shipping_rate_key(at, "SMALL_BOX")).set_value(0.0).run()
    at.button(key="shipping_save_SMALL_BOX").click().run()
    assert "USD金額は0より大きい値を入力してください。" in _texts(at)
    assert len(ShippingRuleRepository().list_history(ShippingType.SMALL_BOX)) == 1
