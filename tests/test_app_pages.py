from pathlib import Path

from streamlit.testing.v1 import AppTest

from llm.mock_provider import DEFAULT_MOCK_PAYLOAD, DEFAULT_RESPONSE_SUMMARY

APP_PATH = Path(__file__).resolve().parents[1] / "app.py"


def _start_app() -> AppTest:
    return AppTest.from_file(str(APP_PATH)).run()


def test_home_opens_technical_case_page():
    at = _start_app()

    at.button(key="open_technical_case").click().run()

    assert at.title[0].value == "営業・技術受付AI"
    assert "Technical Case Agent" in [caption.value for caption in at.caption]
    assert "まだ解析結果はありません" in [text.value for text in at.text]


def test_home_opens_quote_control_page():
    at = _start_app()
    quote_button = at.button(key="open_quote_control")

    assert quote_button.disabled is False
    quote_button.click().run()

    visible_text = [item.value for item in at.text] + [item.value for item in at.markdown]
    caption_text = [item.value for item in at.caption]

    assert at.title[0].value == "見積・価格管理AI"
    assert "Quote & Price Control Agent" in caption_text
    assert "価格表・SKU管理" in [item.value for item in at.subheader] + visible_text
    assert "Deep Trekker 更新情報" in [item.value for item in at.subheader] + visible_text
    assert "SpaceOneマスター照合" in [item.value for item in at.subheader] + visible_text
    assert "まだ価格表は読み込んでいません。" in [item.value for item in at.text]
    assert "現在は開発用の整理処理です" in [item.value for item in at.warning]
    assert any(button.label == "価格表を読み込む" for button in at.button)
    assert any(button.label == "社内マスターをSKUで照合" for button in at.button)
    assert any(expander.label == "Golden Quote Cases（開発用）" for expander in at.expander)
    assert "SKUリンク移行プレビュー" in " ".join([item.value for item in at.subheader] + visible_text + [item.value for item in at.markdown])
    assert any(button.label == "更新情報として整理" for button in at.button)
    assert not any("正式" in (button.label or "") and "反映" in (button.label or "") for button in at.button)
    assert not any(button.label == "Apply" for button in at.button)


def test_analyze_button_shows_mock_results():
    at = _start_app()
    at.button(key="open_technical_case").click().run()

    at.text_input(key="input_case_name").set_value("PipeTrekker 管内点検")
    at.text_input(key="input_customer_name").set_value("サンプル株式会社")
    at.text_area(key="input_customer_inquiry").set_value("直径300mmの管を点検したい。")
    at.button(key="analyze_inquiry").click().run()

    visible_text = [item.value for item in at.text] + [item.value for item in at.markdown]
    warning_text = [item.value for item in at.warning]

    assert "現在は開発用Mock解析を使用しています" in warning_text
    assert DEFAULT_MOCK_PAYLOAD["case_summary"] in visible_text
    assert "管内点検" in " ".join(visible_text)
    assert "点検する管の内径と管種を教えてください。" in " ".join(visible_text)
    assert at.json.len == 1
    assert at.expander[0].label == "解析データを確認"
    assert at.error.len == 0


def test_manufacturer_response_button_shows_mock_matches():
    at = _start_app()
    at.button(key="open_technical_case").click().run()

    at.text_input(key="input_case_name").set_value("PipeTrekker 管内点検")
    at.text_input(key="input_customer_name").set_value("サンプル株式会社")
    at.text_area(key="input_customer_inquiry").set_value("直径300mmの管を点検したい。")
    at.button(key="analyze_inquiry").click().run()

    at.text_area(key="input_manufacturer_response").set_value("メーカーからの返信サンプルです。")
    at.button(key="organize_manufacturer_response").click().run()

    visible_text = [item.value for item in at.text] + [item.value for item in at.markdown]
    caption_text = [item.value for item in at.caption]
    warning_text = [item.value for item in at.warning]

    assert "現在は開発用Mock回答整理を使用しています" in warning_text
    assert "AI整理結果・要確認" in caption_text
    assert DEFAULT_RESPONSE_SUMMARY in visible_text
    assert "回答あり" in visible_text
    assert "質問に含まれていない追加情報" in " ".join(visible_text)
    assert "技術情報として整理" not in " ".join(visible_text)
    assert not any(button.label == "技術情報として登録" for button in at.button)
    assert at.error.len == 0


def test_apply_button_marks_manufacturer_question_applied():
    at = _start_app()
    at.button(key="open_technical_case").click().run()
    at.text_area(key="input_customer_inquiry").set_value("管内点検の相談です。")
    at.button(key="analyze_inquiry").click().run()
    at.text_area(key="input_manufacturer_response").set_value("メーカーからの返信サンプルです。")
    at.button(key="organize_manufacturer_response").click().run()

    apply_buttons = [button for button in at.button if button.label == "この内容で反映"]
    assert apply_buttons
    apply_buttons[0].click().run()

    visible_text = [item.value for item in at.text] + [item.value for item in at.markdown]
    success_text = [item.value for item in at.success]

    assert "確認済みとして反映しました" in success_text
    assert "反映済み" in " ".join([item.value for item in at.caption] + visible_text)
    assert "未反映: 0" in visible_text
    assert "技術情報として整理" in " ".join(visible_text)
    assert any(button.label == "技術情報として登録" for button in at.button)


def test_human_can_register_technical_fact_from_applied_answer():
    at = _start_app()
    at.button(key="open_technical_case").click().run()
    at.text_area(key="input_customer_inquiry").set_value("管内点検の相談です。")
    at.button(key="analyze_inquiry").click().run()
    at.text_area(key="input_manufacturer_response").set_value("メーカーからの返信サンプルです。")
    at.button(key="organize_manufacturer_response").click().run()
    [button for button in at.button if button.label == "この内容で反映"][0].click().run()

    question_id = at.session_state["manufacturer_approval_board"].items[0].question.question_id
    at.text_input(key=f"fact_product_{question_id}").set_value("MAG Utility Crawler")
    at.text_input(key=f"fact_topic_{question_id}").set_value("surface_transition")
    at.text_area(key=f"fact_text_{question_id}").set_value("MAGは異なる面へ連続して移動できない。")
    at.button(key=f"register_fact_button_{question_id}").click().run()

    board_item = at.session_state["manufacturer_approval_board"].items[0]
    success_text = [entry.value for entry in at.success]
    visible_text = [entry.value for entry in at.text] + [entry.value for entry in at.markdown]

    assert "技術情報として登録しました" in success_text
    assert len(board_item.registered_facts) == 1
    assert board_item.registered_facts[0].scope.value == "CASE_ONLY"
    assert board_item.registered_facts[0].confidence.value != "MANUFACTURER_CONFIRMED"
    assert "登録済み技術情報" in " ".join(visible_text)


def test_quote_control_shows_import_and_diff_without_apply():
    from agents.quote_control_agent import diff_price_books, import_price_book
    from tests.price_book_fixtures import previous_master_book, valid_price_book

    at = _start_app()
    at.button(key="open_quote_control").click().run()

    incoming = import_price_book(valid_price_book(), source_price_book="DT40", version="2026-09")
    previous = import_price_book(previous_master_book(), source_price_book="previous")
    at.session_state["price_book_import"] = incoming
    at.session_state["price_book_diff"] = diff_price_books(previous.items, incoming.items)
    at.run()

    visible_text = [item.value for item in at.text] + [item.value for item in at.markdown]
    assert "読込SKU数: 6" in visible_text
    assert "読込Sheet数: 5" in visible_text
    assert "新規SKU" in " ".join(visible_text)
    assert "価格変更" in " ".join(visible_text)
    assert "削除候補" in " ".join(visible_text)
    assert not any("正式" in (button.label or "") and "反映" in (button.label or "") for button in at.button)


def test_quote_control_shows_sku_link_preview_and_manual_fields():
    from agents.quote_control_agent import import_price_book
    from agents.sku_link import build_sku_link_preview
    from parsers.spaceone_master_parser import parse_spaceone_master
    from tests.price_book_fixtures import manufacturer_books_for_reconciliation, spaceone_master_book

    at = _start_app()
    at.button(key="open_quote_control").click().run()

    dt40_file, pt30_file = manufacturer_books_for_reconciliation()
    dt40 = import_price_book(dt40_file, source_price_book="DT40")
    pt30 = import_price_book(pt30_file, source_price_book="PT30")
    spaceone = parse_spaceone_master(spaceone_master_book(), source_name="SO_MASTER")
    at.session_state["sku_link_preview"] = build_sku_link_preview(spaceone.items, dt40, pt30)
    at.run()

    visible_text = [item.value for item in at.text] + [item.value for item in at.markdown]
    joined = " ".join(visible_text)
    assert "総SpaceOne商品: 12" in visible_text
    assert "AUTO_LINKED: 6" in visible_text
    assert "REVIEW_REQUIRED:" in joined
    assert "要確認SKUの手動紐付け" in joined
    assert any(input_box.label == "正式Manufacturer SKU" for input_box in at.text_input)
    assert any(button.label == "このSKUに紐付け" for button in at.button)


def test_back_button_returns_to_home():
    at = _start_app()
    at.button(key="open_technical_case").click().run()
    at.button(key="back_to_home").click().run()

    assert at.title[0].value == "Deep Trekker 業務支援AI"
