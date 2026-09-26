from pathlib import Path

from streamlit.testing.v1 import AppTest

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


def test_analyze_button_shows_pending_message_without_results():
    at = _start_app()
    at.button(key="open_technical_case").click().run()

    at.text_input(key="input_case_name").set_value("PipeTrekker 管内点検")
    at.text_input(key="input_customer_name").set_value("サンプル株式会社")
    at.text_area(key="input_customer_inquiry").set_value("直径300mmの管を点検したい。")
    at.button(key="analyze_inquiry").click().run()

    assert at.info[0].value == "AI解析機能は次のSTEPで接続します"
    assert "まだ解析結果はありません" in [text.value for text in at.text]
    assert at.json.len == 0


def test_back_button_returns_to_home():
    at = _start_app()
    at.button(key="open_technical_case").click().run()
    at.button(key="back_to_home").click().run()

    assert at.title[0].value == "Deep Trekker 業務支援AI"
