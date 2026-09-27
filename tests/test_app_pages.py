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


def test_quote_control_stays_unavailable():
    at = _start_app()
    quote_button = at.button(key="open_quote_control")

    assert quote_button.disabled is True
    assert at.title[0].value == "Deep Trekker 業務支援AI"


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


def test_back_button_returns_to_home():
    at = _start_app()
    at.button(key="open_technical_case").click().run()
    at.button(key="back_to_home").click().run()

    assert at.title[0].value == "Deep Trekker 業務支援AI"
