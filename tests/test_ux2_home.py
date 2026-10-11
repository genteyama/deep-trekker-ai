from tests.test_app_pages import _start_app
from ui.home import _work_summary_items, chunk_items


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


def test_recent_work_chunks_into_at_most_three_columns():
    assert [len(row) for row in chunk_items(list(range(1)), 3)] == [1]
    assert [len(row) for row in chunk_items(list(range(3)), 3)] == [3]
    assert [len(row) for row in chunk_items(list(range(4)), 3)] == [3, 1]
    assert [len(row) for row in chunk_items(list(range(8)), 3)] == [3, 3, 2]
