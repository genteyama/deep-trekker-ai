# Deep Trekker AI - Project Context

引き継ぎ用の要約。Source of Truth は Git / 現在コード（→ 2章）。

Last updated: 2026-10-08（HEAD `9ad88db`）

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
ただし業務上の安全要件・禁止事項（→ 14章）は別途確認する。

## 3. Current Status

- 現在 Phase: **Pricing Policy v1 / 見積・価格管理 Phase — Business Acceptance COMPLETE**
- Price Master Data Quality: **DQ-4 COMPLETE**（2026-10-08、Production SO_MASTER 更新済み。AUTO 116 / REVIEW 2 / EXCLUDED 1 → 12章）。次は DQ-5（SO Master Price Reference Repair）
- HEAD: `1387fc7 Document Pricing Policy v1 completion`（main = origin/main）
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

※ 9680-EXPEET は DQ-3 で正式 Master を 9680-EXPERT に修正済み（→ 12章）。表示文言の例として残している。

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

## 12. Price Master Data Quality / Production Registry

判定: **DQ-4 COMPLETE**（2026-10-08）。DQ-1 / DQ-2 / DQ-3 COMPLETE、DQ-4A / DQ-4B / DQ-4C PASS。

現在の SO Master 分類（Production Registry の active master から）: **AUTO 116 / REVIEW 2 / EXCLUDED 1 / TOTAL 119**

### DQ-3: SO Master の修正（正式 Google Sheet で修正済み）

| Sheet | Cell | 修正前 | 修正後 |
| --- | --- | --- | --- |
| MAG | B16 | 9701-VAC-4K | 9701-MAX-4K |
| PHOTON | B14 | 9680-EXPEET | 9680-EXPERT |
| REVOLUTION | B14 | 7511-DC-NA7511-DC-NAV | 7511-DC-NAV |
| REVOLUTION | B42 | 日付化された値 | Text の SKU `2500-1` |

SO Master 121 行の分類（parse → reconcile → auto-link → `extract_pricing_policies` → `simulate_sales_price_candidates` → quote-time policy resolution）:

| | AUTO | REVIEW | EXCLUDED | TOTAL |
| --- | --- | --- | --- | --- |
| 修正前 | 103 | 17 | 1 | 121 |
| 修正後 | 108 | 12 | 1 | 121 |

### DQ-4: SO Master の修正（正式 Google Sheet で修正済み）

残存 REVIEW を 12 → 2 に削減（AUTO 108 → 116、TOTAL 121 → 119）。FX 165 の標準売価:

| 内容 | SKU | 結果 |
| --- | --- | --- |
| PHOTON DPK の merged SKU を修正 | `8560+9686+8808+8486-100+8552` | AUTO 4,331,000 円 |
| PIVOT DPK 100M（フルキットとして確定） | `8560+8835+8808+8486-100` | AUTO 5,016,000 円 |
| PIVOT DPK 300M（フルキットとして確定） | `8560+8835+8487+8486-300+5278` | AUTO 5,577,000 円 |
| 日付化 SKU を Text SKU に正常化（PHOTON / PIVOT / REVOLUTION） | `9757-2` ×3 | AUTO 649,000 / 649,000 / 677,000 円 |
| 8459 の重複を整理（PHOTON Row 18 側を正式採用、重複側を削除） | `8459` | AUTO 156,000 円 |
| 2105-M3000D の重複を正式 1 行に整理 | `2105-M3000D` | AUTO 8,825,000 円 |

### Production Price Master Registry

DQ-3B で初回 Bootstrap 済み（それ以前の Acceptance / DQ はすべて scratch DB で実施）。

- Production DB: `runtime/deep_trekker.sqlite3`
- Production storage: `runtime/price_masters/`
- Bootstrap で追加されたもの: `price_master_imports` table、`idx_price_master_imports_active`、`idx_price_master_imports_sha`、`runtime/price_masters/{DT40,PT30,QUOTE_CALC,SO_MASTER}/`
- 既存業務 6 table（quote_drafts / approved_quote_snapshots / technical_cases / technical_case_response_revisions / activity_events / customers）の schema / content は不変（row count と canonical hash で確認）。

Active Price Masters:

| Type | import_id | SHA-256 |
| --- | --- | --- |
| DT40 | `DT40-20261008T034155Z-60b1958a` | `f230c85c4ccb49c838abdb8cb11892fbd378d361ff1c926c6ef249e489ceedfe` |
| PT30 | `PT30-20261008T034155Z-4663ccbd` | `34c0516e73675dd0daca8c6bda292078faacd01448b3627997c3efd51fc423f2` |
| QUOTE_CALC | `QUOTE_CALC-20261008T034205Z-2fd41ea2` | `915fdf8cca8ace4ca9833cfbcd518f98d3d1b0b7f747f959646f347b54392412` |
| SO_MASTER | `SO_MASTER-20261008T051104Z-4f6c4b00` | `a7a3bfd87c6b5bd04c6786e2ff88e1e32c23300dace7f82009b6569e36e7bd06` |

- SO_MASTER は DQ-4C で更新。Validation VALID（118 items / 118 policies）、stored path `SO_MASTER/SO_MASTER-20261008T051104Z-4f6c4b00.xlsx`。source の absolute path には依存しない。
- 旧 SO_MASTER `SO_MASTER-20261008T034206Z-32d7a8b0`（SHA-256 `0f603d4a434bbae7176513ca886c1738020ffb8b6a012b8e86209fbdce0a0f59`）は history と stored file を保持したまま inactive。
- DQ-4C の前後で DT40 / PT30 / QUOTE_CALC、既存業務 6 table、コードは不変。

Regression として維持を確認した価格（FX 165、Production Registry の active master から）:

| SKU | 標準売価 |
| --- | --- |
| 9701-MAX-4K | 10,243,000 円 |
| 9680-EXPERT | 5,262,000 円 |
| 7511-DC-NAV | 19,314,000 円 |
| 2500-1 | 4,764,000 円 |
| 9701-MAG-4K | 6,432,000 円 |

- 10800PRO: MANUAL_REVIEW を維持。
- 2601: Manufacturer Master には存在するが、SO row / SO Policy なしを維持。

### Source File Independence

- Downloads などの import 元ファイルは一時的な入力にすぎない。
- import 後は Registry が管理する `runtime/price_masters/<TYPE>/<import_id>.xlsx` を使う。stored path は相対パスで、source の absolute path は保存しない。
- 元ファイルを削除しても active master は利用できる（scratch Registry で元ファイルを rename して確認済み）。

### Rollback

SO Master の rollback（通常はこちらを優先）:

- 旧 version `SO_MASTER-20261008T034206Z-32d7a8b0` を正式な activate 経路で再 activate する（同じ bytes を `import_price_master` に渡すと REACTIVATED になる）。DB の直接編集はしない。

pre-bootstrap 状態への復旧（DQ-3B 以前に戻す場合のみ）:

- Registry に deactivate API はないため、Registry 自体を無かった状態に戻すには DB backup を使う。
- pre-bootstrap backup（repo 外・read-only）: `/Users/user/AI_Work/deep-trekker-ai-backups/20261008_price_master_pre_bootstrap/deep_trekker_before_price_master_bootstrap.sqlite3`
  - SHA-256: `524ac59fd93c1c0fb86d0a87e6183c5ddf2e2ebe481b385594243b5287cc3f14`
- pre-bootstrap 状態へ戻す手順:
  1. app を停止する
  2. production DB を backup から復元する
  3. `runtime/price_masters/` を退避する
  4. app を再起動する
  5. Registry が存在しないことを確認する
- 通常運用ではこの rollback は実行しない。

### 残存 REVIEW（2 件）

1. 10800PRO: intentional MANUAL_REVIEW。修正対象外。
2. 9685: SKU_NOT_FOUND。Manufacturer の確認待ち。類似 SKU から推測して修正しない。

### Known Data Quality Issue: SO Master の価格参照

- SO Master の Manufacturer 価格参照式（`IMPORTRANGE`）に大規模なずれがある。DQ-4A の監査では、79 references のうち 49 references が別 SKU の row を参照している可能性が高い。既知の PRICE_MISMATCH は 34 行。
- Production の見積価格は Manufacturer Master の official MSRP を使うため、現在の見積候補は正常。
- ただし人が SO Master を直接見たときに、誤った価格を見るリスクがある。DQ-5 で扱う（→ 15章）。

### Workbook Format Note

- DQ-4 修正後の export では、SKU 列 B が Text format になり、約 1,000 行まで empty formatted cells がある。
- parser の結果には影響せず、不要な行から item は生成されない。
- Text 化は SKU の日付誤変換を防ぐ点で安全。
- empty formatting の cleanup は必要なら別途行う。DQ-5 の価格参照修正と混ぜて、不用意に範囲を広げない。

## 13. Test Baseline

- full pytest: 676 passed（`pytest -q`）
- `git diff --check`: PASS
- runtime / outputs / 元 Price Master: Acceptance の前後で変更なし（SHA-256 で確認）
- API calls: 0

テストは `tests/conftest.py` が test ごとに SQLite を tmp に分離し、LLM provider を mock 化する。

## 14. Important Safety Rules

- AI が価格・SKU・仕様を推測して確定しない。
- 不明なときは REVIEW_REQUIRED / fail closed にする。
- Customer final price は人が決める。
- Formal Quote の Source は Approved Snapshot のみ。
- 元 Price Master を書き換えない（Acceptance は scratch コピー / scratch DB で行う）。
- runtime / customer data を Git に入れない。
- `.env` / secrets を Git に入れない。
- `git add .` は禁止。commit 前に対象ファイルを明示的に確認する。
- 不可逆な処理・外部処理（送信・外部 API など）は Human in the Loop。

## 15. Known Backlog

v1 完了を止めないもの:

### Audit Trail（v1.1）

- `exchange_rate_set_at`: UI の `submit_exchange_rate` が設定日時を渡しておらず、Approved Snapshot では None。採用為替をいつ決めたかの監査情報として追加を検討する。
- `PriceAdjustment.entered_by`: UI から入力者を渡しておらず None。誰が案件価格を設定したかの監査情報として追加を検討する。

### Price Master Data Quality DQ-5: SO Master Price Reference Repair

目的: SO Master 上の Manufacturer 価格参照を正しい SKU / Manufacturer row に直し、人が Google Sheet 上で見ても誤った MSRP / Dealer / 試算価格を参照しない状態にする（→ 12章 Known Data Quality Issue）。

- Pricing engine のロジック変更ではない。Production の見積は現在正常。
- まず audit する。いきなり 49 箇所を変更しない。
- 推測で修正しない。fuzzy match で自動解決しない。
- 9685 は Manufacturer の確認が取れ次第、別途扱う。

### Performance

- 初回の Quote 作成に約 11 秒かかる。
- 約 3MB の Workbook の再読込が主因の候補。import_id / SHA 単位の parsed master cache などを検討する。

## 16. Next Phase Candidates

Pricing Policy v1 には追加せず、別 Phase として扱う。

優先候補:

1. Price Master Data Quality DQ-5: SO Master Price Reference Repair（DQ-4 まで COMPLETE）
2. Performance
3. v1.1 Audit Trail

次 Phase を始める前に、業務上の優先順位を確認する。

## 17. Development Rules

- repo 全体を毎回読まない。`rg` で探し、必要なファイルだけ読む。
- targeted test を回し、Phase 終了時に full test を回す。
- ついでの改善はしない。
- Step / Phase ごとに checkpoint commit する。
- Context が肥大化したら compact / new Session にする。
- Git / current code を Source of Truth とする。
