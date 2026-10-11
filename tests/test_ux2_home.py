from tests.test_app_pages import _start_app
from ui.home import _work_summary_items


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


def test_home_renders_work_before_compact_feature_menu():
    at = _start_app()
    section_titles = [
        item.value
        for item in at.markdown
        if "portal-section-title" in item.value
    ]

    summary_index = next(index for index, value in enumerate(section_titles) if "進行中の業務" in value)
    work_index = next(index for index, value in enumerate(section_titles) if "進行中の案件" in value)
    menu_index = next(index for index, value in enumerate(section_titles) if "機能メニュー" in value)

    assert summary_index < work_index < menu_index
    assert [metric.label for metric in at.metric] == ["営業・技術", "見積", "進行中 合計"]
    assert sum("portal-card is-compact" in item.value for item in at.markdown) == 3
    assert at.button(key="open_technical_case").disabled is False
    assert at.button(key="open_quote_control").disabled is False
    assert at.button(key="open_activity_ledger").disabled is False
