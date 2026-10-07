# Deep Trekker AI - Project Context

引き継ぎ用の要約。Source of Truth は Git / 現在コード（→ 2章）。

Last updated: 2026-10-07（HEAD `c634c82`）

## 1. Project Purpose

スペースワンの Deep Trekker / PIPETREKKER 関連業務（販売・技術対応・見積・履歴管理など）を支援する業務システム。

目標:

- 業務時間削減・手作業削減
- 見積ミス削減
- 属人化低減（Deep Trekker 知識が少ない担当者でも扱えること）
- AI は推測で価格・仕様を確定しない
- Human in the Loop を維持する

## 2. Source of Truth

優先順位:

1. Git / 現在コード
2. 現在有効な設定（`config/` など）
3. この PROJECT_CONTEXT
4. 過去チャット

PROJECT_CONTEXT とコードが矛盾した場合は、原則コード / Git を優先する。
ただし業務上の安全要件・禁止事項（→ 13章）は別途確認する。

## 3. Current Status

- 現在 Phase: **Pricing Policy v1 / 見積・価格管理 Phase — Business Acceptance COMPLETE**
- HEAD: `c634c82 Clarify pricing review reasons`（main = origin/main）
- full pytest: 676 passed
- working tree: clean

## 4. Current Main Capabilities

| 機能 | 概要 | 主なファイル |
| --- | --- | --- |
| Technical Case Agent | 技術問い合わせの整理・メーカー回答の取り込み | `agents/technical_case_agent.py`, `ui/technical_case*.py` |
| Quote / Pricing workflow | Step 1〜5（構成 → 原価・売価 → 顧客表示 → 承認 → 出力） | `ui/quote_workspace.py`, `agents/quote_builder.py` |
| Activity Ledger | 作業履歴の記録・出力 | `agents/activity_log.py`, `ui/activity_ledger.py` |
| Price Master Registry | DT40 / PT30 / SO_MASTER / QUOTE_CALC の検証・SHA 管理・有効化 | `agents/price_master.py` |
| Pricing Policy | SpaceOne 標準売価の解決 | `agents/pricing_policy.py` |
| Exchange Rate provenance | 採用為替と市場参考為替・理由・設定者の保持 | `agents/quote_builder.py`, `ui/pricing_display.py` |
| Customer Price Rounding | 顧客向け価格の 1,000 円単位丸め | `agents/pricing_policy.py` |
| Issuer Snapshot | 承認時に発行元情報を固定 | `agents/issuer.py`, `config/issuer.json` |
| Formal PDF / Excel export | Approved Snapshot からの正式帳票 | `agents/quote_export.py`, `agents/quote_pdf.py` |
| Approval / Revision flow | 承認・不変 Snapshot・改訂 Draft | `agents/quote_approval.py` |

## 5. Pricing Policy v1 - Confirmed Specification

正式な Pricing Policy type（`models/enums.py` `PricingPolicyType`）:

- `MSRP_MULTIPLIER`
- `FIXED_JPY`
- `MANUAL_REVIEW`

Dealer multiplier や SPECIAL_FORMULA は正式な type として追加しない。安全に計算できないものは `MANUAL_REVIEW` にする。

標準売価:

```
Manufacturer MSRP × 採用為替 × SpaceOne multiplier
```

顧客向けの標準売価は **1,000 円単位・Decimal ROUND_HALF_UP**（`round_customer_price_jpy`）。

例: 35,437 USD × 165 × 1.1 = 6,431,815.5 → **6,432,000 円**

- 内部原価・Dealer JPY・Landed Cost には顧客向けの千円丸めを適用しない。
- FIXED_JPY は Master 値を尊重する。
- 不明・不整合のときは fail closed（REVIEW、価格を作らない）。

## 6. Exchange Rate

- 市場参考為替と採用為替を分けて扱う。
  - 市場参考為替（参考日・参考ソース・buffer を含む）は参考表示のみ。
  - 実計算に使うのは `QuoteDraft.exchange_rate`（採用為替）。人が確定する。
- FX を変更したとき:
  - 原価を再計算する
  - 標準売価を再計算する
  - 案件売価（final price）は自動変更しない
- 採用理由（例: `MARKET_PLUS_BUFFER`）・メモ・設定者を保持する。
- Step 2 → 3 → 2 の移動後も、保存値から FX metadata が復元される（確認済み）。

## 7. Price Adjustment

- 標準売価と案件売価は別の値として扱う。案件売価は人が決める。
- 標準売価との差額・率・理由コード（例: `COMPETITIVE_RESPONSE`）・メモを Adjustment として記録する。
- 既存の Adjustment 履歴は「その時点で人が設定した履歴」であり、後の FX 変更で自動的に書き換えない。
- 案件売価も 1,000 円単位でなければ保存しない。

## 8. Issuer

正式 Source は `config/issuer.json`:

- 株式会社スペースワン
- 〒963-8833 福島県郡山市香久池1-17-3
- 東京営業所：〒110-0005 東京都台東区上野1-20-1-5F
- TEL: 024-954-9930

承認時の流れ: config → `IssuerSnapshot` → `ApprovedQuoteSnapshot` に固定。

- 通常の Draft は issuer を持たない。
- 過去の Approved Snapshot は不変（後で config が変わっても変わらない）。
- Revision Draft は旧 issuer を引き継がず、再承認時点の現行 config を使う。
- Draft に明示的な issuer を持つもの（historical fixture など）は、その明示値を優先する。
- issuer config が読めない場合、承認はブロックされる。

## 9. Formal Quote Documents

- 正式 PDF / Excel の Source は `ApprovedQuoteSnapshot` のみ。Draft からは正式帳票を出さない。
- 顧客帳票に出さないもの:
  - Dealer 価格
  - Landed Cost
  - 粗利
  - MSRP
  - Pricing multiplier
  - 標準売価（案件売価と異なる場合）
  - 内部 FX metadata
  - Adjustment の内部メモ
  - Master SHA
  - REVIEW の内部情報
- 帳票の算術は `sum(lines) == subtotal` かつ `subtotal + tax == total` が条件。一致しなければ正式出力しない。
- 出力の際に内部用語の漏洩スキャンを行う（`scan_customer_pdf_leaks` / `scan_customer_workbook_leaks`）。

## 10. Pricing Review Reasons

確定している表示（`locales/ja.json` / `ui/pricing_display.py` `standard_review_reason`）:

| 例 SKU | 表示 |
| --- | --- |
| 2601 | SpaceOne標準売価の設定がありません |
| 9680-EXPEET | メーカーSKUを特定できません |
| 10800PRO | 特殊な価格式のため確認が必要です |

REVIEW_REQUIRED のときは価格を推測しない（fail closed）。

## 11. Final Business Acceptance

判定: **PASS**（2026-10-07）

方法: 実 Price Master 4 本を scratch DB に取り込み、Streamlit AppTest で Quote 作成 → Step 1〜5 → 承認 → 正式 PDF / Excel まで、実 UI フローを通した。

MAG 9701-MAG-4K:

| 項目 | 値 |
| --- | --- |
| Manufacturer Master | DT40 |
| MSRP | 35,437 USD |
| Dealer | 21,262.2 USD |
| Policy | MSRP_MULTIPLIER ×1.1 |
| 採用為替 | 165（市場参考 162 + buffer 3, MARKET_PLUS_BUFFER） |
| 標準売価 | 6,432,000 円（raw 6,431,815.5） |
| 案件売価 | 6,000,000 円 |
| Adjustment | COMPETITIVE_RESPONSE −432,000 円 |
| Landed Cost | 3,974,337.19 円（丸めなし） |
| Dealer 原価 | 3,508,263 円（丸めなし） |

正式帳票の金額:

```
6,000,000 + 2,192,000 + 2,155,000 + 352,000 + 120,000 (shipping)
subtotal 10,819,000
tax       1,081,900
total    11,900,900
```

- PDF・Excel とも上記と完全一致し、内部情報の漏洩はなかった。
- Step 2 → 3 → 2 を 2 往復して FX metadata の復元を確認。原価・標準売価・案件売価に意図しない変更はなかった。
- 帳票を再出力しても Approved Snapshot は不変だった。

## 12. Test Baseline

- full pytest: 676 passed（`pytest -q`）
- `git diff --check`: PASS
- runtime / outputs / 元 Price Master: Acceptance の前後で変更なし（SHA-256 で確認）
- API calls: 0

テストは `tests/conftest.py` が test ごとに SQLite を tmp に分離し、LLM provider を mock 化する。

## 13. Important Safety Rules

- AI が価格・SKU・仕様を推測して確定しない。
- 不明なときは REVIEW_REQUIRED / fail closed にする。
- Customer final price は人が決める。
- Formal Quote の Source は Approved Snapshot のみ。
- 元 Price Master を書き換えない（Acceptance は scratch コピー / scratch DB で行う）。
- runtime / customer data を Git に入れない。
- `.env` / secrets を Git に入れない。
- `git add .` は禁止。commit 前に対象ファイルを明示的に確認する。
- 不可逆な処理・外部処理（送信・外部 API など）は Human in the Loop。

## 14. Known Backlog

v1 完了を止めないもの:

### Audit Trail（v1.1）

- `exchange_rate_set_at`: UI の `submit_exchange_rate` が設定日時を渡しておらず、Approved Snapshot では None。採用為替をいつ決めたかの監査情報として追加を検討する。
- `PriceAdjustment.entered_by`: UI から入力者を渡しておらず None。誰が案件価格を設定したかの監査情報として追加を検討する。

### Price Master Data Quality

- REVIEW_REQUIRED になる typo / merged SKU / exact-match できないデータを整理する。
- fuzzy match で自動解決しない。正式 Master の修正を優先する。

### Performance

- 初回の Quote 作成に約 11 秒かかる。
- 約 3MB の Workbook の再読込が主因の候補。import_id / SHA 単位の parsed master cache などを検討する。

## 15. Next Phase Candidates

Pricing Policy v1 には追加せず、別 Phase として扱う。

優先候補:

1. Price Master Data Quality
2. Performance
3. v1.1 Audit Trail

次 Phase を始める前に、業務上の優先順位を確認する。

## 16. Development Rules

- repo 全体を毎回読まない。`rg` で探し、必要なファイルだけ読む。
- targeted test を回し、Phase 終了時に full test を回す。
- ついでの改善はしない。
- Step / Phase ごとに checkpoint commit する。
- Context が肥大化したら compact / new Session にする。
- Git / current code を Source of Truth とする。
