from pathlib import Path

from streamlit.testing.v1 import AppTest

from llm.mock_provider import DEFAULT_MOCK_PAYLOAD, DEFAULT_RESPONSE_SUMMARY

APP_PATH = Path(__file__).resolve().parents[1] / "app.py"


def _start_app() -> AppTest:
    return AppTest.from_file(str(APP_PATH)).run()


def test_home_dashboard_shows_both_work_kinds():
    at = _start_app()
    visible = " ".join(
        [item.value for item in at.text]
        + [item.value for item in at.markdown]
        + [item.value for item in at.caption]
    )
    assert "進行中の案件" in visible
    assert "営業・技術受付AI" in visible
    assert "見積・価格管理AI" in visible
    filter_labels = []
    for radio in at.radio:
        filter_labels.extend(getattr(radio, "options", None) or [])
        if getattr(radio, "label", None):
            filter_labels.append(radio.label)
    assert any("進行中" in str(label) for label in filter_labels) or at.radio
    assert at.button(key="open_technical_case").disabled is False
    assert at.button(key="open_quote_control").disabled is False
    assert "入力不足のため次へ進めません" not in visible


def test_incomplete_technical_case_does_not_block_actions():
    at = _start_app()
    at.button(key="open_technical_case").click().run()
    visible = " ".join(
        [item.value for item in at.text]
        + [item.value for item in at.markdown]
        + [item.value for item in at.caption]
    )
    assert at.button(key="analyze_inquiry").disabled is False
    assert at.button(key="organize_manufacturer_response").disabled is False
    assert at.button(key="save_technical_case").disabled is False
    assert at.button(key="new_technical_case").disabled is False
    assert "入力不足のため次へ進めません" not in visible
    assert "進捗" in visible
    assert "要確認" in visible


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
    assert any("1 構成確認" in (button.label or "") for button in at.button)
    assert any("2 原価・標準売価" in (button.label or "") for button in at.button)
    assert any("3 顧客向け見積" in (button.label or "") for button in at.button)
    assert any("4 レビュー・承認" in (button.label or "") for button in at.button)
    assert any("5 帳票出力" in (button.label or "") for button in at.button)
    assert any(expander.label == "詳細・開発情報" for expander in at.expander)
    assert "価格表・SKU管理" in [item.value for item in at.subheader] + visible_text
    assert "Deep Trekker 更新情報" in [item.value for item in at.subheader] + visible_text
    assert "SpaceOneマスター照合" in [item.value for item in at.subheader] + visible_text
    assert "SpaceOne販売価格ポリシー" in [item.value for item in at.subheader] + visible_text
    assert "案件原価・粗利試算" in [item.value for item in at.subheader] + visible_text
    assert "見積ドラフト作成" in [item.value for item in at.subheader] + visible_text
    assert "まだ価格表は読み込んでいません。" in [item.value for item in at.text]
    assert "現在は開発用の整理処理です" in [item.value for item in at.warning]
    assert any(button.label == "価格表を読み込む" for button in at.button)
    assert any(button.label == "社内マスターをSKUで照合" for button in at.button)
    assert any(expander.label == "Golden Quote Cases（開発用）" for expander in at.expander)
    assert any(button.label == "IHI Supplier QuoteをDT40/PT30と照合" for button in at.button)
    assert any(button.label == "案件原価を試算" for button in at.button)
    assert any(button.label == "IHI PHOTON 見積ドラフト" for button in at.button)
    assert any(button.label == "IHI MAG 見積ドラフト" for button in at.button)
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
    assert any(expander.label == "解析データを確認" for expander in at.expander)
    assert at.error.len == 0
    assert any(button.key == "new_technical_case" for button in at.button)
    assert any(button.key == "save_technical_case" for button in at.button)
    assert "最近の案件" in " ".join(visible_text)
    assert any(expander.label == "確認済み技術情報一覧" for expander in at.expander)


def test_mag_inquiry_shows_retrieved_approved_facts():
    at = _start_app()
    at.button(key="open_technical_case").click().run()
    at.text_area(key="input_customer_inquiry").set_value(
        "MAG Utility Crawlerで鋼製円筒タンクの水中肉厚測定を検討。側面と底面。測定した場所を把握したい。"
    )
    at.button(key="analyze_inquiry").click().run()

    visible_text = " ".join(
        [item.value for item in at.text] + [item.value for item in at.markdown] + [item.value for item in at.caption]
    )
    assert "参照した承認済み技術情報" in visible_text
    assert "異なる面へ連続して移動できない" in visible_text
    assert "自己位置を把握する機能はない" in visible_text
    assert "Cygnus" in visible_text
    assert "ROVと超音波肉厚計" in visible_text
    assert "この案件への適用は未確定" in visible_text
    assert "45kgf" not in visible_text
    assert "ATEX" not in visible_text
    assert DEFAULT_MOCK_PAYLOAD["case_summary"] in visible_text


def test_app_starts_without_claude_api_key(monkeypatch):
    monkeypatch.setenv("TECHNICAL_CASE_PROVIDER", "anthropic")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "")
    monkeypatch.setenv("ANTHROPIC_MODEL", "claude-opus-5")
    monkeypatch.setenv("ANTHROPIC_ENABLE_FALLBACKS", "false")

    at = _start_app()
    assert not at.exception

    at.button(key="open_technical_case").click().run()
    assert not at.exception

    visible_text = " ".join(
        [item.value for item in at.text] + [item.value for item in at.markdown]
    )
    assert any("AI Provider" in (expander.label or "") for expander in at.expander)
    assert "Claude" in visible_text
    assert "claude-opus-5" in visible_text
    assert "未接続" in visible_text
    assert "ANTHROPIC_API_KEY" not in visible_text
    assert "sk-ant" not in visible_text
    assert not any("開発用Mock解析" in (item.value or "") for item in at.warning)

    at.text_area(key="input_customer_inquiry").set_value("管内点検の相談です。")
    at.button(key="analyze_inquiry").click().run()
    assert not at.exception
    assert "Claude APIキーが設定されていません" in [item.value for item in at.error]
    visible_after = " ".join(
        [item.value for item in at.text] + [item.value for item in at.markdown]
    )
    assert DEFAULT_MOCK_PAYLOAD["case_summary"] not in visible_after


def test_claude_connection_test_without_key_does_not_send_customer_data(monkeypatch):
    monkeypatch.setenv("TECHNICAL_CASE_PROVIDER", "anthropic")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "")

    at = _start_app()
    at.button(key="open_technical_case").click().run()
    at.text_input(key="input_case_name").set_value("機密案件A")
    at.text_input(key="input_customer_name").set_value("秘密顧客")
    at.text_area(key="input_customer_inquiry").set_value("顧客の生メール全文")

    at.button(key="claude_connection_test").click().run()
    assert not at.exception
    assert "Claude APIキーが設定されていません" in [item.value for item in at.error]
    visible_text = " ".join(
        [item.value for item in at.text] + [item.value for item in at.markdown]
    )
    assert DEFAULT_MOCK_PAYLOAD["case_summary"] not in visible_text
    assert "ANTHROPIC_API_KEY" not in visible_text


def test_app_starts_with_ollama_provider_without_api_key(monkeypatch):
    monkeypatch.setenv("TECHNICAL_CASE_PROVIDER", "ollama")
    monkeypatch.setenv("OLLAMA_MODEL", "qwen3.5:9b")
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)

    at = _start_app()
    assert not at.exception

    at.button(key="open_technical_case").click().run()
    assert not at.exception

    visible_text = " ".join(
        [item.value for item in at.text] + [item.value for item in at.markdown]
    )
    assert any("AI Provider" in (expander.label or "") for expander in at.expander)
    assert "Local AI (Ollama)" in visible_text
    assert "qwen3.5:9b" in visible_text
    assert "未接続" in visible_text
    assert any(getattr(button, "key", None) == "ollama_connection_test" for button in at.button)
    assert not any(getattr(button, "key", None) == "claude_connection_test" for button in at.button)
    assert "ANTHROPIC_API_KEY" not in visible_text
    assert "sk-ant" not in visible_text
    assert not any("開発用Mock解析" in (item.value or "") for item in at.warning)


def test_app_starts_with_gemini_provider_without_api_key(monkeypatch):
    monkeypatch.setenv("TECHNICAL_CASE_PROVIDER", "gemini")
    monkeypatch.setenv("GEMINI_MODEL", "gemini-3.8-flash")
    monkeypatch.setenv("GEMINI_API_KEY", "")

    at = _start_app()
    assert not at.exception

    at.button(key="open_technical_case").click().run()
    assert not at.exception

    visible_text = " ".join(
        [item.value for item in at.text] + [item.value for item in at.markdown]
    )
    assert any("AI Provider" in (expander.label or "") for expander in at.expander)
    assert "Gemini" in visible_text
    assert "gemini-3.8-flash" in visible_text
    assert "未接続" in visible_text
    assert any(getattr(button, "key", None) == "gemini_connection_test" for button in at.button)
    assert not any(getattr(button, "key", None) == "claude_connection_test" for button in at.button)
    assert not any(getattr(button, "key", None) == "ollama_connection_test" for button in at.button)
    assert "GEMINI_API_KEY" not in visible_text
    assert "AIza" not in visible_text
    assert not any("開発用Mock解析" in (item.value or "") for item in at.warning)

    at.text_area(key="input_customer_inquiry").set_value("管内点検の相談です。")
    at.button(key="analyze_inquiry").click().run()
    assert not at.exception
    assert "Gemini APIキーが設定されていません" in [item.value for item in at.error]
    visible_after = " ".join(
        [item.value for item in at.text] + [item.value for item in at.markdown]
    )
    assert DEFAULT_MOCK_PAYLOAD["case_summary"] not in visible_after


def test_gemini_connection_test_without_key_does_not_send_customer_data(monkeypatch):
    monkeypatch.setenv("TECHNICAL_CASE_PROVIDER", "gemini")
    monkeypatch.setenv("GEMINI_API_KEY", "")

    at = _start_app()
    at.button(key="open_technical_case").click().run()
    at.text_input(key="input_case_name").set_value("機密案件A")
    at.text_input(key="input_customer_name").set_value("秘密顧客")
    at.text_area(key="input_customer_inquiry").set_value("顧客の生メール全文")

    at.button(key="gemini_connection_test").click().run()
    assert not at.exception
    assert "Gemini APIキーが設定されていません" in [item.value for item in at.error]
    visible_text = " ".join(
        [item.value for item in at.text] + [item.value for item in at.markdown]
    )
    assert DEFAULT_MOCK_PAYLOAD["case_summary"] not in visible_text
    assert "GEMINI_API_KEY" not in visible_text


def test_saved_technical_case_can_resume_after_new_case():
    at = _start_app()
    at.button(key="open_technical_case").click().run()
    at.text_input(key="input_case_name").set_value("再開確認案件")
    at.text_input(key="input_customer_name").set_value("再開株式会社")
    at.text_area(key="input_customer_inquiry").set_value("直径300mmの管を点検したい。")
    at.button(key="analyze_inquiry").click().run()
    at.button(key="new_technical_case").click().run()
    resume_buttons = [button for button in at.button if (button.key or "").startswith("resume_technical_case_")]
    assert resume_buttons
    resume_buttons[0].click().run()
    visible_text = [item.value for item in at.text] + [item.value for item in at.markdown]
    assert DEFAULT_MOCK_PAYLOAD["case_summary"] in visible_text
    assert at.session_state["input_customer_inquiry"] == "直径300mmの管を点検したい。"
    assert at.session_state["technical_case_run"].provider_name == "mock"


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


def _quote_date_widget(elements, key):
    matches = [item for item in elements if getattr(item, "key", None) == key]
    assert matches, f"missing widget {key}"
    return matches[0]


def test_quote_date_widgets_do_not_raise_and_follow_auto_rule():
    from datetime import date

    from agents.quote_approval import apply_ihi_photon_human_final_fixture
    from agents.quote_dates import add_one_calendar_month, date_widget_keys, tokyo_today
    from tests.test_quote_builder import _photon_draft

    at = _start_app()
    at.button(key="open_quote_control").click().run()

    draft = _photon_draft()
    keys = date_widget_keys(draft.quote_draft_id)
    at.session_state["quote_draft"] = draft
    at.session_state["quote_workspace_step"] = 4
    at.run()

    assert not at.exception
    assert at.session_state[keys["issue"]] == tokyo_today()
    assert at.session_state[keys["valid"]] == add_one_calendar_month(tokyo_today())
    assert at.session_state[keys["auto"]] is True

    _quote_date_widget(at.date_input, keys["issue"]).set_value(date(2026, 9, 27)).run()
    assert not at.exception
    assert at.session_state[keys["valid"]] == date(2026, 10, 27)

    _quote_date_widget(at.checkbox, keys["auto"]).set_value(False).run()
    _quote_date_widget(at.date_input, keys["valid"]).set_value(date(2026, 10, 31)).run()
    _quote_date_widget(at.date_input, keys["issue"]).set_value(date(2026, 11, 1)).run()
    assert not at.exception
    assert at.session_state[keys["valid"]] == date(2026, 10, 31)

    _quote_date_widget(at.checkbox, keys["auto"]).set_value(True).run()
    assert not at.exception
    assert at.session_state[keys["valid"]] == date(2026, 12, 1)

    apply_ihi_photon_human_final_fixture(at.session_state["quote_draft"])
    at.session_state[keys["pending"]] = True
    at.run()
    assert not at.exception
    assert at.session_state[keys["issue"]] == date(2026, 9, 26)
    assert at.session_state[keys["valid"]] == date(2026, 10, 31)
    assert at.session_state[keys["auto"]] is False


def test_quote_date_human_final_button_does_not_raise_after_widgets():
    from datetime import date

    from agents.quote_dates import date_widget_keys
    from tests.test_quote_builder import _photon_draft

    at = _start_app()
    at.button(key="open_quote_control").click().run()
    draft = _photon_draft()
    keys = date_widget_keys(draft.quote_draft_id)
    at.session_state["quote_draft"] = draft
    at.session_state["quote_workspace_step"] = 4
    at.run()
    assert not at.exception

    at.button(key="photon_human_final").click().run()
    assert not at.exception
    assert at.session_state[keys["issue"]] == date(2026, 9, 26)
    assert at.session_state[keys["valid"]] == date(2026, 10, 31)
    assert at.session_state[keys["auto"]] is False


def test_quote_workspace_shows_only_selected_step_and_keeps_draft():
    from agents.quote_approval import apply_ihi_photon_human_final_fixture
    from agents.quote_dates import date_widget_keys
    from tests.test_quote_approval import _approve, _ready_photon
    from tests.test_quote_builder import _photon_draft

    at = _start_app()
    at.button(key="open_quote_control").click().run()
    draft = _photon_draft()
    draft_id = draft.quote_draft_id
    keys = date_widget_keys(draft_id)
    at.session_state["quote_draft"] = draft
    at.session_state["quote_workspace_step"] = 1
    at.run()
    assert not at.exception
    assert at.session_state["quote_draft"].quote_draft_id == draft_id
    assert not any(getattr(item, "key", None) == keys["issue"] for item in at.date_input)
    assert not any(getattr(item, "key", None) == "export_spaceone_xlsx" for item in at.button)
    assert not any(getattr(item, "key", None) == "approve_quote_snapshot" for item in at.button)

    at.button(key="quote_step_3").click().run()
    assert at.session_state["quote_workspace_step"] == 3
    assert at.session_state["quote_draft"].quote_draft_id == draft_id
    visible = " ".join([item.value for item in at.text] + [item.value for item in at.markdown])
    assert "PHOTON" in visible or "DeepTrekker" in visible
    assert not any(getattr(item, "key", None) == keys["issue"] for item in at.date_input)

    at.button(key="quote_step_4").click().run()
    at.checkbox(key="confirm_configuration").set_value(True).run()
    at.session_state[keys["issue"]]  # widget exists
    assert at.session_state["confirm_configuration"] is True
    assert not any(getattr(item, "key", None) == "approve_quote_snapshot" for item in at.button)
    assert any(getattr(item, "key", None) == "check_quote_approval" for item in at.button)

    apply_ihi_photon_human_final_fixture(at.session_state["quote_draft"])
    at.session_state[keys["pending"]] = True
    at.run()
    at.button(key="quote_step_1").click().run()
    assert at.session_state["quote_draft"].issue_date == "2026-09-26"
    assert at.session_state["quote_draft"].total_jpy == 7876000
    assert at.session_state["quote_persist_confirm_configuration"] is True
    at.button(key="quote_step_4").click().run()
    assert at.session_state["quote_draft"].issue_date == "2026-09-26"
    assert at.session_state["confirm_configuration"] is True
    assert at.session_state[keys["issue"]].isoformat() == "2026-09-26"

    at.session_state["quote_workspace_step"] = 5
    at.run()
    assert any("帳票出力には承認が必要です" in (item or "") for item in [entry.value for entry in at.warning] + [entry.value for entry in at.text])
    assert not any(getattr(item, "key", None) == "export_spaceone_xlsx" for item in at.button)
    assert not any(getattr(item, "key", None) == "export_spaceone_pdf" for item in at.button)

    ready = _ready_photon()
    _, snapshot = _approve(ready)
    at.session_state["quote_draft"] = ready
    at.session_state["approved_quote_snapshot"] = snapshot
    at.session_state["quote_workspace_step"] = 5
    at.run()
    assert not at.exception
    assert any(getattr(item, "key", None) == "export_spaceone_xlsx" for item in at.button)
    assert any(getattr(item, "key", None) == "export_spaceone_pdf" for item in at.button)
    assert snapshot.total_jpy == 7876000
    assert abs(snapshot.gross_margin_rate - 0.29598) < 0.00001
    assert at.session_state["approved_quote_snapshot"].approved_quote_snapshot_id == snapshot.approved_quote_snapshot_id


def test_saved_draft_can_be_resumed_after_session_is_cleared():
    from datetime import date

    from agents.quote_approval import apply_ihi_photon_human_final_fixture
    from agents.quote_dates import date_widget_keys
    from repositories.sqlite_quote_repository import SqliteQuoteRepository
    from tests.test_quote_builder import _photon_draft

    draft = _photon_draft()
    apply_ihi_photon_human_final_fixture(draft)
    repo = SqliteQuoteRepository()
    repo.save_draft(
        draft,
        {
            "step": 4,
            "confirm_configuration": True,
            "confirm_presentation": True,
            "confirm_sales_price": True,
            "confirm_remarks": False,
            "selected_remarks": list(draft.remarks),
            "auto_valid_until": False,
        },
    )

    at = _start_app()
    at.button(key="open_quote_control").click().run()
    resume = next((button for button in at.button if button.label == "作業を再開"), None)
    assert resume is not None
    resume.click().run()

    keys = date_widget_keys(draft.quote_draft_id)
    assert not at.exception
    assert at.session_state["quote_draft"].total_jpy == 7876000
    assert at.session_state["quote_draft"].issue_date == "2026-09-26"
    assert at.session_state["quote_draft"].valid_until == "2026-10-31"
    assert at.session_state["quote_workspace_step"] == 4
    assert at.session_state["confirm_configuration"] is True
    assert at.session_state[keys["issue"]] == date(2026, 9, 26)
    assert at.session_state[keys["valid"]] == date(2026, 10, 31)
    assert any(getattr(item, "key", None) == "save_quote_draft" for item in at.button)


def test_new_quote_buttons_remain_after_draft_is_created():
    from tests.test_quote_builder import _photon_draft

    at = _start_app()
    at.button(key="open_quote_control").click().run()
    at.session_state["quote_draft"] = _photon_draft()
    at.session_state["quote_workspace_step"] = 1
    at.run()

    assert not at.exception
    assert at.session_state["quote_draft"] is not None
    assert any(button.label == "IHI PHOTON 見積ドラフト" for button in at.button)
    assert any(button.label == "IHI MAG 見積ドラフト" for button in at.button)
    assert any(expander.label == "新しい見積を作成" for expander in at.expander)
    assert any(getattr(item, "key", None) == "save_quote_draft" for item in at.button)


def test_pending_form_values_resume_without_applying_or_widget_exception():
    from datetime import date

    from agents.quote_dates import date_widget_keys
    from repositories.sqlite_quote_repository import SqliteQuoteRepository
    from tests.test_quote_builder import _photon_draft
    from ui.quote_persistence import customer_description_widget_key, manual_price_widget_key
    from ui.quote_steps import persist_review_key

    draft = _photon_draft()
    base = next(line for line in draft.configuration_lines if line.manufacturer_sku == "9680-BASE")
    customer = next(line for line in draft.customer_lines if line.line_kind == "PRODUCT")
    remark = draft.remark_candidates[0].text
    official_base = base.final_sales_price_jpy
    official_shipping = next(line for line in draft.customer_lines if line.line_kind == "SHIPPING").amount_jpy
    official_tax = draft.tax_rate
    official_description = customer.description
    official_remarks = list(draft.remarks)
    keys = date_widget_keys(draft.quote_draft_id)

    at = _start_app()
    at.button(key="open_quote_control").click().run()
    at.session_state["quote_draft"] = draft
    at.session_state["quote_workspace_step"] = 2
    at.run()
    assert not at.exception
    at.text_input(key=manual_price_widget_key(base.line_id)).set_value("3540000").run()
    at.text_input(key="input_draft_shipping_price").set_value("870000").run()
    at.button(key="quote_step_3").click().run()
    at.text_input(key="input_draft_tax_rate").set_value("0.10").run()
    at.text_area(key=customer_description_widget_key(customer.customer_quote_line_id)).set_value("途中の説明").run()
    at.button(key="quote_step_4").click().run()
    at.multiselect(key="input_selected_remarks").set_value([remark]).run()
    at.date_input(key=keys["issue"]).set_value(date(2026, 9, 27)).run()
    at.checkbox(key=keys["auto"]).set_value(True).run()
    at.button(key="save_quote_draft").click().run()
    assert not at.exception
    assert at.session_state["quote_draft"].configuration_lines[0].final_sales_price_jpy == official_base
    assert next(line for line in at.session_state["quote_draft"].customer_lines if line.line_kind == "SHIPPING").amount_jpy == official_shipping
    assert at.session_state["quote_draft"].tax_rate == official_tax

    loaded = SqliteQuoteRepository().get_draft(draft.quote_draft_id)
    assert loaded.ui_state["pending_final_prices"][base.line_id] == "3540000"
    assert loaded.ui_state["pending_shipping_customer_price"] == "870000"
    assert loaded.ui_state["pending_tax_rate"] == "0.10"
    assert loaded.ui_state["pending_customer_descriptions"][customer.customer_quote_line_id] == "途中の説明"
    assert remark in loaded.ui_state["selected_remarks"]
    assert loaded.draft.remarks == official_remarks
    assert next(
        line for line in loaded.draft.customer_lines if line.customer_quote_line_id == customer.customer_quote_line_id
    ).description == official_description

    resumed = _start_app()
    resumed.button(key="open_quote_control").click().run()
    resume = next((button for button in resumed.button if button.label == "作業を再開"), None)
    assert resume is not None
    resume.click().run()
    assert not resumed.exception
    assert resumed.session_state["quote_draft"].quote_draft_id == draft.quote_draft_id
    resumed.button(key="quote_step_2").click().run()
    assert not resumed.exception
    assert resumed.session_state[manual_price_widget_key(base.line_id)] == "3540000"
    assert resumed.session_state["input_draft_shipping_price"] == "870000"
    assert resumed.session_state["quote_draft"].configuration_lines[0].final_sales_price_jpy == official_base
    resumed.button(key="quote_step_3").click().run()
    assert not resumed.exception
    assert resumed.session_state["input_draft_tax_rate"] == "0.10"
    assert resumed.session_state[customer_description_widget_key(customer.customer_quote_line_id)] == "途中の説明"
    resumed.button(key="quote_step_4").click().run()
    assert not resumed.exception
    assert remark in resumed.session_state["input_selected_remarks"]
    assert resumed.session_state[keys["issue"]] == date(2026, 9, 27)
    assert resumed.session_state[keys["auto"]] is True
    persist_key = persist_review_key("input_selected_remarks")
    assert persist_key in resumed.session_state
    assert resumed.session_state[persist_key] == resumed.session_state["input_selected_remarks"]


def test_export_inputs_resume_without_changing_snapshot():
    from tests.test_quote_approval import _approve, _ready_photon
    from repositories.sqlite_quote_repository import SqliteQuoteRepository

    draft = _ready_photon()
    _, snapshot = _approve(draft)
    original_id = snapshot.approved_quote_snapshot_id
    repo = SqliteQuoteRepository()
    repo.save_snapshot(snapshot)
    repo.save_draft(
        draft,
        {
            "step": 5,
            "pending_official_quote_number": "8195",
            "pending_generated_by": "Gen Oteyama",
        },
    )

    at = _start_app()
    at.button(key="open_quote_control").click().run()
    resume = next((button for button in at.button if button.label == "作業を再開"), None)
    assert resume is not None
    resume.click().run()
    assert not at.exception
    if at.session_state["quote_workspace_step"] != 5:
        at.button(key="quote_step_5").click().run()
    assert not at.exception
    assert at.session_state["input_official_quote_number"] == "8195"
    assert at.session_state["input_export_generated_by"] == "Gen Oteyama"
    assert at.session_state["approved_quote_snapshot"].approved_quote_snapshot_id == original_id
    assert at.session_state["approved_quote_snapshot"].official_quote_number is None
    assert at.session_state["approved_quote_snapshot"].total_jpy == 7876000


def test_brand_logos_are_local_assets():
    from ui.theme import BRAND_LOGOS, DEEPTREKKER_LOGO, PIPETREKKER_LOGO, SPACEONE_LOGO

    assert DEEPTREKKER_LOGO.exists()
    assert PIPETREKKER_LOGO.exists()
    assert SPACEONE_LOGO.exists()
    assert all(path.exists() and path.suffix == ".png" for path, _alt in BRAND_LOGOS)
