from types import SimpleNamespace

from tests.test_app_pages import _start_app
from ui.home import _hero_summary_items, _work_summary_items
from ui.work_status import KIND_QUOTE


def test_work_summary_totals_current_workload():
    portal = {
        "kind_technical": "営業・技術",
        "kind_quote": "見積",
        "work_summary_total": "進行中 合計",
        "count_unit": "件",
    }

    assert _work_summary_items(portal, 2, 3) == [
        ("営業・技術", "2 件"),
        ("見積", "3 件"),
        ("進行中 合計", "5 件"),
    ]


def test_home_uses_compact_work_first_layout_without_feature_menu():
    at = _start_app()
    section_titles = [
        item.value
        for item in at.markdown
        if "portal-section-title" in item.value
    ]

    summary_index = next(index for index, value in enumerate(section_titles) if "進行中の業務" in value)
    work_index = next(index for index, value in enumerate(section_titles) if "進行中の案件" in value)

    assert summary_index < work_index
    assert not at.metric
    assert any("home-summary-grid" in item.value for item in at.markdown)
    assert not any("<div class='portal-card" in item.value for item in at.markdown)
    assert not any("機能メニュー" in item.value for item in at.markdown)
    assert at.button(key="sidebar_nav_technical").disabled is False
    assert at.button(key="sidebar_nav_quote").disabled is False
    assert at.button(key="sidebar_nav_activity").disabled is False


def test_hero_summary_adds_review_total_between_counts_and_total():
    portal = {"kind_technical": "営業・技術", "kind_quote": "見積", "work_summary_total": "進行中 合計", "count_unit": "件"}
    items = [
        {"kind": KIND_QUOTE, "summary": SimpleNamespace(completed=3, total=5, review_required=4)},
        {"kind": KIND_QUOTE, "summary": SimpleNamespace(completed=1, total=5, review_required=0)},
    ]

    assert _hero_summary_items(portal, 1, 2, items) == [
        ("営業・技術", "1 件", ""),
        ("見積", "2 件", ""),
        ("要確認", "4 件", "is-review"),
        ("進行中 合計", "3 件", "is-total"),
    ]


def test_home_shows_next_actions_and_price_master_panels():
    at = _start_app()
    html = " ".join(item.value for item in at.markdown)

    assert "次にやること" in html
    assert "価格マスター" in html
    assert "home-master-row" in html
