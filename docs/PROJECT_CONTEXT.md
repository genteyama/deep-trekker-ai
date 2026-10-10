# Deep Trekker AI - Project Context

引き継ぎ用の要約。Source of Truth は Git / 現在コード（→ 2章）。

Last updated: 2026-10-09（v1.1.0 baseline `1512f22`。Phase A〜A.4 の commit は Git を正とする）

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

- 現在 Phase: **Phase B — Business Case Close / Reopen + Status Quick View**
- v1.1.0 Online Multi-device MVP: **完成済み**。main baseline `1512f22112deff7f6d4b2512c273e5a2dac24ff9`（tag `v1.1.0`）
- 旧記載の HEAD `e746ca9` はそれ以前の checkpoint。この文書とコードが矛盾する場合は Git / current code を優先
- full pytest: 811 passed（`pytest -q`、2026-10-10 DQ-5B Preview）
- Price Master Data Quality: **DQ-4 COMPLETE**。**DQ-5A audit only COMPLETE**（修正は未実施。→ 12章 / 15章）

### v1.2 Phase A: Manufacturer Online Price Master Sync

オンラインのメーカー価格表は、見積計算に直接使わない。

メーカー Online Price Data → 取得 → 既存 Active Master との差分 → validation → 人間確認 → 新しい Price Master Snapshot として登録・有効化 → 見積計算。

- 対象は DT40 / PT30。Price Master 管理画面の「メーカー価格表を確認」で差分を見て、問題がないときだけ「新しいPrice Masterとして登録・有効化」する。
- 比較は normalized SKU の完全一致と正式な価格列（Dealer Price / MSRP）。行番号・行順は価格変更にしない。SKU と価格が同じなら新しい Snapshot は作らない。
- 同一 SKU で MSRP または Dealer Price が食い違う場合は reject し、既存 Active Master を維持する。シートをまたいで同一価格の SKU は、既存 parser どおり 1 SKU にまとめる。
- 取得失敗、空、xlsx でない、parser 不能、必須列不足、想定外のブック構造、validation error では自動 activate しない。
- 通常運用の Source of Truth は PostgreSQL `manufacturer_price_sources`（ローカルは SQLite）。価格マスター管理の「オンライン価格表設定」から URL を保存する。URL 保存だけでは Snapshot / Active Master / Quote 価格は変わらない。
- DB にまだ行がない初期移行時だけ、環境変数 / Streamlit Secrets → `config/manufacturer_price_sources.json` の順で bootstrap 値を読む。通常運用で複数箇所を編集しない。
- Online Sync 対象は DT40 / PT30。SPECTRA_GOLD の Online Source は `FUTURE`（オンライン連携保留）で、URL 保存と xlsx 接続確認までを維持し、Online review / activation 対象には入れない。
- Source Registry は URL、有効状態、parser profile、lifecycle、最終確認結果、updated_at / updated_by、row_version を保持し、古い画面からの更新を reject する。
- Online review は確認時点の Active Master import_id と Source key / URL / enabled / row_version を固定する。承認時にいずれかが変わっていれば `ONLINE_REVIEW_STALE` で reject し、最新版の再確認を要求する。
- PostgreSQL migration は更新後の `deploy/postgres_schema.sql` を既存 DB に再実行する（`CREATE TABLE IF NOT EXISTS` の追加のみ。既存テーブルは削除・変更しない）。
- bootstrap 設定:
  - 環境変数または Streamlit Secrets: `DT40_ONLINE_PRICE_SOURCE_URL`、`PT30_ONLINE_PRICE_SOURCE_URL`、`SPECTRA_GOLD_ONLINE_PRICE_SOURCE_URL`
  - `config/manufacturer_price_sources.json` の各 `url`（空なら未設定）
  - 非公開Google SpreadsheetはStreamlit Secretsの `[google_price_source_service_account]` を使用する。scopeはDrive read-only。秘密鍵・tokenはDB、provenance、ログへ保存しない。
  - Google SpreadsheetはService Account設定時にDrive API v3 `files.export`でxlsx取得する。権限がない場合も、公開Sheetなら従来のpublic xlsx exportへfallbackする。`google-api-python-client`は使用しない。
- 新しい Snapshot の出所は、既存の import_id / sha256 / filename / validation に加え、`validation_summary.online_source`（source_id、source_key、source_url、source row_version、fetched_at、filename、sha256、auth_mode）。ApprovedQuoteSnapshot のprovenanceは変更していない。
- SPECTRA_GOLD は `PriceMasterType` として手動 xlsx upload / validation / human activation / immutable history に対応。専用 parser は `SPECTRA` sheet だけを読み、`Part Number` / `Description` / `Spectra`（MSRP）/ `Gold`（Dealer）と source marker を厳格に検証する。ONYX その他の sheet / Gold 列は混入させない。
- SPECTRA の価格は source の明示値だけを使い、Gold 率等から逆算しない。片側欠損、TBD、CONTACT PRODUCT TO QUOTE、0 USD、負数は manual review として正式価格に採用せず、価格未確定 line は承認を block する。明示された0・負数は監査用 occurrence に原本値を保持する。
- priced SPECTRA SKU は完全一致で Quote の official manufacturer candidate に利用する。対応する SO_MASTER policy がなければ顧客売価を推測せず REVIEW とする。
- 通常の新規見積UIから、Active SPECTRA_GOLD内の完全一致SKUを指定して単品Quote Draftを作成できる。SPECTRA Master未設定・SKU不一致・QUOTE_CALC未設定ではDraftを作らない。DT40 / PT30からSPECTRA SKUを補完しない。
- SPECTRA単品見積の輸送原価は人間の明示入力だけを使う。国際輸送または国内送料が未入力ならpending placeholderでtotal landed costを未確定にし、Draftは作成できるが承認をblockする。
- SPECTRA_GOLD Online Source は引き続き `FUTURE`。将来 Online Sync を有効化するときは、同じ SPECTRA parser / Price Master import path を再利用する。
- Quote 価格式、為替、SO_MASTER、QUOTE_CALC、顧客最終価格、正式帳票は変更していない。9701-MAG-4K / FX 165 = 6,432,000 円を維持。

### v1.2.1 UX Patch

- `FUTURE` のSPECTRA Online Sourceは通常画面で「オンライン連携：停止中」と表示し、URL編集・有効化・保存・接続確認・過去の接続エラーを表示しない。Registry値とbackend機能は維持する。
- Quoteの内部warning / Enum / reasonは変更せず、通常UIだけを業務ユーザー向けの日英表現へ変換する。承認判定・Pricing・Snapshotには変更なし。
- 既存Draft / validation / shipping placeholderの事実から、販売価格・国際輸送原価・国内送料・税率・納期等の要確認理由を重複なく短く表示し、詳細でも内部英語を直接表示しない。

### Phase B: Business Case Close / Reopen + Status Quick View

- `CaseLifecycleStatus`（ACTIVE / CLOSED）を追加。TechnicalCaseStatusの工程完了、Archive、Trashとは独立し、Close / Reopenでworkflow statusを変更しない。
- Close reason、closed_at / by、memoをTechnicalCaseRecordとPostgreSQL / SQLiteのtop-level columnsへ保存する。既存行はACTIVE扱い。SQLiteは`ensure_columns`、PostgreSQLはrepository起動時と`deploy/postgres_schema.sql`のidempotent `ADD COLUMN IF NOT EXISTS`でmigrationする。
- Close / Reopenは既存row_versionによるoptimistic lockを通し、`CASE_CLOSED` / `CASE_REOPENED`をActivity Ledgerへappend-onlyで記録する。Duplicate / Derived caseはACTIVEかつClose metadataなしで開始する。
- Homeに「終了案件」と決定論的Status Quick Viewを追加。保存済みworkflow summaryと最新Activityだけを使い、AI / 外部APIは使用しない。
- CLOSED案件は通常workflow mutation UIを表示せず、Reopen、Archive / Trash、履歴参照を優先する。
- Quote / Pricing / Price Master / ApprovedQuoteSnapshotの仕様は変更していない。
- Production SmokeはPASS。保存timestampはUTCのまま、業務画面の日時はAsia/Tokyoで表示する。
- Technical CaseのHome cardとQuick Viewの進捗は、案件本体と同じ7工程workflowを表示する。Quoteの進捗計算は変更していない。

### v1 First Launch Readiness（2026-10-08）

判定: **PASS**。Production DB / price_masters の scratch コピー上で Streamlit AppTest により実施（Production DB・price_masters・outputs は前後で SHA-256 不変、外部通信 0）。

- 起動: `streamlit run app.py` で起動エラーなし（health ok / HTTP 200）。
- Quote: 9701-MAG-4K、FX 165 → 標準売価 6,432,000 円 → 顧客向け見積 → Review → Approval → 正式 PDF / Excel（合計 11,900,900 円）。再出力後も Approved Snapshot 不変。
- 正式帳票は Approved Snapshot のみ（QuoteDraft からの出力は拒否）。PDF / Excel に Dealer / 原価 / MSRP / policy 等の内部情報なし。
- 10800PRO: MANUAL_REVIEW（自動価格なし）。9685: SKU_NOT_FOUND → REVIEW（推測価格なし）。
- Regression（FX 165）: 9701-MAX-4K 10,243,000 / 9680-EXPERT 5,262,000 / 7511-DC-NAV 19,314,000 / 2500-1 4,764,000 円。
- Technical Case: 受付 → 要件整理 → 技術情報確認 → メーカー確認 → 回答整理（反映）→ 顧客回答 → 完了、保存。Activity Ledger の Word / PDF 出力。外部メール送信なし。
- Production Registry: active 4 本（DT40 / PT30 / QUOTE_CALC / SO_MASTER `SO_MASTER-20261008T051104Z-4f6c4b00`）、すべて VALID（→ 12章）。

Known limitations:

- SO Google Sheet Manufacturer row references contain known mismatches. Until DQ-5 completion, quote price Source of Truth is application / Manufacturer Master, not SO displayed reference price.
- 10800PRO: intentional MANUAL_REVIEW。
- 9685: Manufacturer 確認待ち（REVIEW 維持）。

Next:

- 2026-10-09 から実業務を兼ねた v1 pilot operation。
- DQ-5 hardening は運用を止めず別 Step で実施。

## 4. Current Main Capabilities

| 機能 | 概要 | 主なファイル |
| --- | --- | --- |
| Technical Case Agent | 技術問い合わせの整理・メーカー回答の取り込み | `agents/technical_case_agent.py`, `ui/technical_case*.py` |
| Quote / Pricing workflow | Step 1〜5（構成 → 原価・売価 → 顧客表示 → 承認 → 出力） | `ui/quote_workspace.py`, `agents/quote_builder.py` |
| Activity Ledger | 作業履歴の記録・出力 | `agents/activity_log.py`, `ui/activity_ledger.py` |
| Price Master Registry | DT40 / PT30 / SPECTRA_GOLD / SO_MASTER / QUOTE_CALC の検証・SHA 管理・有効化。DT40 / PT30 はオンライン確認、SPECTRA_GOLD は手動 upload と人間の承認後にだけ新しい Snapshot を有効化する | `agents/price_master.py`, `agents/online_price_master.py` |
| Manufacturer Price Source Registry | PostgreSQL / SQLite で DT40 / PT30 / SPECTRA_GOLD の URL・状態・監査情報・row_version を共有管理 | `repositories/manufacturer_price_source_repository.py`, `ui/price_master.py` |
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

- SO Master の Manufacturer 価格参照式（`IMPORTRANGE`）に row ずれがある。DQ-4A の過去参考値は 79 references / 49 suspected wrong / 34 PRICE_MISMATCH rows。DQ-5A は現在の Active Master で再監査し、この過去値へ合わせていない。
- Production の見積価格は Manufacturer Master の official MSRP を使うため、現在の見積候補は正常。
- ただし人が SO Master を直接見たときに、誤った価格を見るリスクがある。DQ-5 で扱う（→ 15章）。

### Workbook Format Note

- DQ-4 修正後の export では、SKU 列 B が Text format になり、約 1,000 行まで empty formatted cells がある。
- parser の結果には影響せず、不要な行から item は生成されない。
- Text 化は SKU の日付誤変換を防ぐ点で安全。
- empty formatting の cleanup は必要なら別途行う。DQ-5 の価格参照修正と混ぜて、不用意に範囲を広げない。

### Helper sheet namespace（`_SRC_`）

- sheet 名が `_SRC_` で始まる sheet は SO Master の helper sheet（Manufacturer data の参照用ミラー）。
- parser（`parsers/spaceone_master_parser.py` `HELPER_SHEET_PREFIX`）は `_SRC_` sheet を price item source として parse しない。hidden / visible は判定に使わない。

## 13. Test Baseline

- Phase B Production Smoke: PASS（Close、終了案件、Quick View、Reopen、workflow status保持、通常workflow復帰）
- v1.3.0 display patch: user-facing timestamps are Asia/Tokyo; persisted timestamps remain UTC; Technical Case progress uses the 7-step workflow; Quote progress logic is unchanged
- Phase B targeted pytest: 214 passed（Business lifecycle、migration、Activity、Technical Case、Home、multi-device、Quote / SPECTRA regression）
- v1.3.0 display targeted pytest: 31 passed（datetime、Home、Quick View、Technical workflow、Phase B UI）
- DQ-5A targeted pytest: 153 passed（reference audit、SpaceOne parser、SKU link、pricing policy、price master）
- DQ-5B targeted pytest: 190 passed（repair preview、DQ-5A、parser、reconciliation、pricing、SPECTRA）
- full pytest: 811 passed（`pytest -q`、2026-10-10）
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

### Price Master Data Quality DQ-5A: SO Master Price Reference Audit

判定: **DQ-5A COMPLETE / audit only**（2026-10-10）。Google Sheet、Production Registry、Price Master、Quote は変更していない。

Active inputs:

- `SO_MASTER-20261008T051104Z-4f6c4b00`
- `DT40-20261008T034155Z-60b1958a`
- `PT30-20261008T034155Z-4663ccbd`

結果（MSRP / Dealer を別 field として監査）:

- SO items 119 / reference fields 238
- CORRECT 102
- EXACT_REPAIRABLE 64 fields / unique SO rows 32
- NO_REFERENCE 2 fields。Formulaがないセルは `safe_to_repair = false`。期待cellは監査情報として残せるが、新しい IMPORTRANGE は人間確認なしに追加しない。
- AMBIGUOUS_OCCURRENCE 66 fields / 21 SKUs
- SKU_NOT_FOUND 2 fields（9685 の MSRP / Dealer）
- MANUAL_REVIEW 2 fields（legacy shipping）
- displayed price mismatch 21 unique SO rows（MSRP 21 / Dealer 21）
- `safe_to_repair` は、既存の単一 Manufacturer reference が期待cellと異なり、exact active occurrence が一意な場合だけ。fuzzy / 類似 SKU は未使用。
- 9685 は数値のみで formula がなく、Manufacturer Master に exact SKU がない。`safe_to_repair = false`。Pricing Policy は REVIEW / SKU_NOT_FOUND のまま。
- 10800PRO の参照 cell は A-200 の exact row と一致。Pricing Policy の MANUAL_REVIEW は変更していない。
- 過去参考値（79 / 49 / 34）とは集計単位が違う。現在の Active Master の結果を優先する。
- 監査出力は `runtime/dq5_audit/`。Git へは入れない。
- DQ-5B で人間確認後に repair する。今回の workbook 修正は 0。

### Price Master Data Quality DQ-5B: SO Master Price Reference Repair Preview

判定: **DQ-5B PREVIEW COMPLETE**（2026-10-10）。正式Google Sheet、Production Registry、元Active
workbook、Quoteは変更していない。

- Fresh DQ-5Aで64 existing exact references / 32 SO rowsを確認してから、COPYへ64件を一括適用。件数またはSource SHAが変わればbatch全体を停止する。
- Formulaは既存URL、IFERROR wrapper、fallbackを保持し、Manufacturer sheet / cell rangeだけを変更する。workbook切替は禁止。
- Preview再監査は対象64 / 64がCORRECT。logical diffも計画対象64 formula cellsだけ。
- NO_REFERENCE 2、AMBIGUOUS 66、SKU_NOT_FOUND 2、MANUAL_REVIEW 2は変更していない。9685も変更なし。
- fallbackは監査のみで変更していない（match 4 / mismatch 42 / unavailable 18）。
- Preview xlsxはformula差分とvalidationの確認専用で、正式upload sourceではない。openpyxl保存後はcached
  formula valueが再計算されない場合があるため、cached値を修正済みの証拠にしない。
- DQ-5CでHuman Review後に正式Google Sheetの対象cellへ適用し、fresh export後に最終reference auditとprice mismatch確認を行う。
- 出力は`runtime/dq5_repair/`（Repair Plan CSV/JSON、Human Review CSV、logical diff JSON、Preview xlsx）。Gitへは入れない。
- Pricing engineのロジック変更はない。Productionの見積は現在正常。

### Performance

- 初回の Quote 作成に約 11 秒かかる。
- 約 3MB の Workbook の再読込が主因の候補。import_id / SHA 単位の parsed master cache などを検討する。

## 16. Next Phase Candidates

Pricing Policy v1 には追加せず、別 Phase として扱う。

v1.2.0 / v1.2.1はProduction Release済み。Phase B開始時のmain HEADは`3bdf93f`。

優先候補:

1. Price Master Data Quality DQ-5C: Human Review後の正式Google Sheet修正とfresh export再監査
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
