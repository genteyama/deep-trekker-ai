from pathlib import Path

from streamlit.testing.v1 import AppTest

from agents.activity_catalog import display_day, load_activity_rows
from agents.activity_log import append_activity_event, get_activity_repository
from repositories.sqlite_quote_repository import SqliteQuoteRepository
from repositories.sqlite_technical_case_repository import SqliteTechnicalCaseRepository
from tests.test_activity_ledger import _saved_case
from ui.navigation import PAGE_TECHNICAL_CASE

APP_PATH = Path(__file__).resolve().parents[1] / "app.py"
ADVANCED_KEYS = (
    "activity_date_from",
    "activity_date_to",
    "activity_filter_end_users",
    "activity_filter_products",
    "activity_include_archived",
)
EXPORT_KEYS = (
    "activity_export_word",
    "activity_export_pdf",
    "activity_export_csv_selected",
    "activity_export_csv_all",
)


def _markdown(at) -> list[str]:
    return [item.value for item in at.markdown]


def _expander_of(at, key: str):
    found = {}

    def walk(block, expander=None):
        current = expander
        if "expand" in str(getattr(block, "type", "")):
            current = block
        if getattr(block, "key", None) == key:
            found["expander"] = current
            return
        children = getattr(block, "children", None) or {}
        for child in children.values():
            walk(child, current)
            if "expander" in found:
                return

    walk(at._tree)
    return found.get("expander")


def _open_ledger(tmp_path):
    database = tmp_path / "activity.sqlite3"
    case_repo = SqliteTechnicalCaseRepository(database)
    quote_repo = SqliteQuoteRepository(database)
    parent = _saved_case(case_repo, title="肉厚測定", customer="IHI検査計測", end_user="造船所")
    child = _saved_case(case_repo, title="派生肉厚", customer="IHI検査計測", end_user="造船所")
    child.parent_case_id = parent.case_id
    case_repo.save_case(child)
    append_activity_event(
        get_activity_repository(database),
        event_type="CASE_UPDATED",
        entity_kind="case",
        entity_id=parent.case_id,
        occurred_at="2026-11-02T01:00:00+00:00",
    )
    at = AppTest.from_file(str(APP_PATH))
    at.session_state["technical_case_repository"] = case_repo
    at.session_state["quote_repository"] = quote_repo
    at.run()
    at.button(key="sidebar_nav_activity").click().run()
    rows = load_activity_rows(case_repo, quote_repo, get_activity_repository(database))
    return at, parent, child, rows


def _summary_values(at) -> list[str]:
    summary = next(value for value in _markdown(at) if "<div class='activity-summary-grid'>" in value)
    return [part.split("<", 1)[0] for part in summary.split("activity-summary-value'>")[1:]]


def _shown_label(at) -> str:
    return next(value for value in _markdown(at) if "<div class='activity-selection-bar'>" in value)


def _titles(at) -> list[str]:
    return [value for value in _markdown(at) if "<div class='activity-td activity-td-title'>" in value]


def _open_varied_ledger(tmp_path):
    database = tmp_path / "activity-filter.sqlite3"
    case_repo = SqliteTechnicalCaseRepository(database)
    quote_repo = SqliteQuoteRepository(database)
    alpha = _saved_case(case_repo, title="アルファ案件", customer="アルファ社", end_user="現場A")
    beta = _saved_case(case_repo, title="ベータ案件", customer="ベータ社", end_user="現場B")
    append_activity_event(
        get_activity_repository(database),
        event_type="CASE_UPDATED",
        entity_kind="case",
        entity_id=alpha.case_id,
        occurred_at="2026-12-01T01:00:00+00:00",
    )
    at = AppTest.from_file(str(APP_PATH))
    at.session_state["technical_case_repository"] = case_repo
    at.session_state["quote_repository"] = quote_repo
    at.run()
    at.button(key="sidebar_nav_activity").click().run()
    return at, alpha, beta


def test_widget_filter_and_sort_apply_on_the_same_run(tmp_path):
    at, _alpha, _beta = _open_varied_ledger(tmp_path)
    assert "表示 2件" in _shown_label(at)
    assert _summary_values(at) == ["2", "0", "0", "0", "2"]
    assert "アルファ案件" in _titles(at)[0]

    at.text_input(key="activity_filter_keyword").set_value("アルファ案件").run()
    assert "表示 1件" in _shown_label(at)
    assert _summary_values(at) == ["1", "0", "0", "0", "1"]
    assert any("アルファ案件" in value for value in _titles(at))
    assert not any("ベータ案件" in value for value in _titles(at))

    at.button(key="activity_reset_filters").click().run()
    assert at.text_input(key="activity_filter_keyword").value == ""
    assert at.selectbox(key="activity_sort_field").value == "last_activity_at"
    assert at.radio(key="activity_sort_dir").value is True
    assert "表示 2件" in _shown_label(at)
    assert any("アルファ案件" in value for value in _titles(at))
    assert any("ベータ案件" in value for value in _titles(at))

    at.multiselect(key="activity_filter_customers").set_value(["ベータ社"]).run()
    assert "表示 1件" in _shown_label(at)
    assert _summary_values(at)[0] == "1"
    assert any("ベータ案件" in value for value in _titles(at))
    assert not any("アルファ案件" in value for value in _titles(at))

    at.button(key="activity_reset_filters").click().run()
    at.selectbox(key="activity_sort_field").set_value("title").run()
    assert at.selectbox(key="activity_sort_field").value == "title"
    assert "ベータ案件" in _titles(at)[0]
    assert "アルファ案件" in _titles(at)[1]


def test_summary_is_compact_and_filters_stay_split(tmp_path):
    at, _parent, _child, _rows = _open_ledger(tmp_path)
    summary = next(value for value in _markdown(at) if "<div class='activity-summary-grid'>" in value)

    assert summary.count("activity-summary-card") == 5
    for label in ("総件数", "問い合わせ", "見積", "完了", "進行中"):
        assert label in summary
    assert list(at.metric) == []
    assert at.text_input(key="activity_filter_keyword")
    assert at.multiselect(key="activity_filter_customers")
    assert at.multiselect(key="activity_filter_categories")
    assert at.multiselect(key="activity_filter_statuses")
    advanced = next(item for item in at.expander if item.label == "詳細フィルター")
    assert advanced.proto.expanded is False
    for key in ADVANCED_KEYS:
        expander = _expander_of(at, key)
        assert expander is not None
        assert expander.label == "詳細フィルター"
    for key in (
        "activity_filter_keyword",
        "activity_filter_customers",
        "activity_filter_categories",
        "activity_filter_statuses",
        "activity_sort_field",
    ):
        assert _expander_of(at, key) is None
    assert at.selectbox(key="activity_sort_field").value == "last_activity_at"
    assert at.radio(key="activity_sort_dir").value is True


def test_reset_sort_and_selection_keep_existing_behavior(tmp_path):
    at, parent, child, _rows = _open_ledger(tmp_path)
    at.text_input(key="activity_filter_keyword").set_value("造船").run()
    at.selectbox(key="activity_sort_field").set_value("customer").run()
    at.button(key="activity_reset_filters").click().run()

    assert at.text_input(key="activity_filter_keyword").value == ""
    assert at.selectbox(key="activity_sort_field").value == "last_activity_at"
    assert at.radio(key="activity_sort_dir").value is True
    assert at.button(key="activity_reset_filters").label == "フィルターをリセット"

    at.button(key="activity_select_all").click().run()
    selected = at.session_state["activity_selected"].selected
    assert f"case:{parent.case_id}" in selected
    assert f"case:{child.case_id}" in selected
    at.button(key="activity_deselect_all").click().run()
    assert at.session_state["activity_selected"].selected == set()


def test_dense_table_keeps_open_navigation_and_collapsed_exports(tmp_path):
    at, parent, child, rows = _open_ledger(tmp_path)
    parent_row = next(row for row in rows if row.entity_id == parent.case_id)
    child_row = next(row for row in rows if row.entity_id == child.case_id)
    headers = [value for value in _markdown(at) if "<div class='activity-th'" in value]

    assert len(headers) == 8
    header_text = " ".join(headers)
    for label in ("選択", "最終活動", "顧客 / End User", "区分 / 機種", "案件名", "対応ステータス", "関連元", "開く"):
        assert label in header_text
    assert "No." not in header_text
    assert "DATE" not in header_text
    assert "最終更新" not in header_text

    activity = display_day(parent_row.last_activity_at)
    activity_cell = next(value for value in _markdown(at) if activity in value and "activity-primary-date" in value)
    assert f"作成: {display_day(parent_row.date)}" in activity_cell
    customer_cell = next(value for value in _markdown(at) if "IHI検査計測" in value and "activity-primary" in value)
    assert "End User: 造船所" in customer_cell
    category_cell = next(value for value in _markdown(at) if "営業・技術案件" in value)
    assert parent_row.product in category_cell
    assert "activity-category-badge" in category_cell
    assert "activity-secondary" in category_cell
    assert any("activity-td-title" in value and "肉厚測定" in value for value in _markdown(at))
    assert any("activity-td-title" in value and "派生肉厚" in value for value in _markdown(at))
    assert any("activity-status-badge" in value and "解析済み" in value for value in _markdown(at))
    assert any(
        "activity-td-title" not in value and "activity-primary" not in value and child_row.title not in value and "肉厚測定" in value and "activity-td" in value
        for value in _markdown(at)
    )
    assert at.button(key=f"activity_open_{parent_row.row_id}")

    at.button(key=f"activity_open_{parent_row.row_id}").click().run()
    assert at.session_state["current_page"] == PAGE_TECHNICAL_CASE
    assert any("record-header" in value and "肉厚測定" in value for value in _markdown(at))

    at = _open_ledger(tmp_path)[0]
    export = next(item for item in at.expander if item.label == "レポート出力")
    assert export.proto.expanded is False
    for key in EXPORT_KEYS:
        assert at.button(key=key)
        expander = _expander_of(at, key)
        assert expander is not None
        assert expander.label == "レポート出力"


def test_activity_table_wrap_rules_stay_scoped():
    from ui.activity_ledger import TABLE_WEIGHTS
    from ui.styles import APP_CSS

    assert len(TABLE_WEIGHTS) == 8
    assert TABLE_WEIGHTS[4] > TABLE_WEIGHTS[2] > TABLE_WEIGHTS[5]
    cell_rule = APP_CSS.split(".activity-td {", 1)[1].split("}", 1)[0]
    assert "overflow-wrap: normal" in cell_rule
    assert "word-break: normal" in cell_rule
    assert "overflow-wrap: anywhere" not in cell_rule
    title_rule = APP_CSS.split(".activity-td-title .activity-primary {", 1)[1].split("}", 1)[0]
    assert "white-space: normal" in title_rule
    assert "overflow-wrap: anywhere" in title_rule
    nowrap_rule = APP_CSS.split(".activity-primary-date,", 1)[1].split("}", 1)[0]
    assert ".activity-category-badge" in nowrap_rule
    assert ".activity-status-badge" in nowrap_rule
    assert "white-space: nowrap" in nowrap_rule
    header_rule = APP_CSS.split(".activity-th {", 1)[1].split("}", 1)[0]
    assert "word-break: keep-all" in header_rule
    global_button = APP_CSS.split("div.stButton > button", 1)[1].split("}", 1)[0]
    assert "min-height: 40px" in global_button
    open_button = APP_CSS.split('[data-testid="stHorizontalBlock"]:has(.activity-td) [data-testid="stButton"] button {', 1)[1].split("}", 1)[0]
    assert "white-space: nowrap" in APP_CSS.split('[data-testid="stHorizontalBlock"]:has(.activity-td) [data-testid="stButton"] button,', 1)[1].split("}", 1)[0]
    assert "min-height: 30px" in open_button
    assert "min-height: 40px" not in open_button
    assert ".block-container { padding-top: 1.2rem; max-width: 1240px; }" in APP_CSS
