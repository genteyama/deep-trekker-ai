from types import SimpleNamespace

from ui.quote_list import filter_quote_list_rows, quote_list_rows


def _item(identifier, customer, subject, status="DRAFT"):
    return SimpleNamespace(
        quote_draft_id=identifier,
        version=1,
        customer_name=customer,
        subject=subject,
        configuration_name="CUSTOM",
        status=status,
        updated_at="2026-11-21T10:00:00+00:00",
    )


def test_quote_list_is_quote_only_searchable_and_can_show_financials():
    items = [
        _item("Q-1", "株式会社エコー", "PIVOT見積"),
        _item("Q-2", "株式会社IHI検査計測", "PHOTON見積", "APPROVED"),
    ]
    drafts = {
        "Q-1": SimpleNamespace(
            draft=SimpleNamespace(
                subtotal_ex_tax_jpy=8500000,
                economics_result=SimpleNamespace(gross_profit_jpy=2400000, gross_margin_rate=0.282),
            )
        ),
        "Q-2": SimpleNamespace(
            draft=SimpleNamespace(
                subtotal_ex_tax_jpy=7000000,
                economics_result=SimpleNamespace(gross_profit_jpy=2000000, gross_margin_rate=0.286),
            )
        ),
    }
    rows = quote_list_rows(items, load_draft=lambda quote_id, version: drafts[quote_id])
    assert len(rows) == 2
    assert rows[0]["売上(税抜)"] == "¥8,500,000"
    assert rows[0]["粗利"] == "¥2,400,000"
    assert rows[0]["粗利率"] == "28.2%"
    assert rows[1]["状態"] == "承認済み"
    assert [row["見積ID"] for row in filter_quote_list_rows(rows, keyword="エコー")] == ["Q-1"]
    assert [row["見積ID"] for row in filter_quote_list_rows(rows, statuses=["承認済み"])] == ["Q-2"]
