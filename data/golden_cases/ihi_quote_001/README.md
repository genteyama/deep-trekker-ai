# IHI_QUOTE_001 Golden Quote Case

## 表示名

IHI検査計測 MAG / PHOTON 肉厚測定提案

## このGolden Caseの目的

株式会社IHI検査計測向けに、実際に作成した見積フローを、今後の Pricing Policy / Landed Cost / Quote Engine の Acceptance Test として使える形に固定したものです。

再現している業務フローは次です。

1. Deep Trekker から Supplier Quote を受領する
2. メーカー見積内容に問題がある
3. DT40 / PT30 のメーカー原典と照合する
4. 必要構成を SpaceOne 側で補正する
5. MAG案 / PHOTON案として顧客見積を作成する

## 3つのSource

| Source | 位置づけ |
|---|---|
| Deep Trekker Supplier Quote | 照合対象。Manufacturer Source of Truth ではない |
| SpaceOne MAG Quote 8194 | 実績 Expected Business Output |
| SpaceOne PHOTON Quote 8195 | 実績 Expected Business Output |

メーカー価格の正は DT40 / PT30 です。

## Supplier Quote を正解にしないこと

この Supplier Quote は、そのまま正しい Supplier Cost として扱ってはいけません。

- 一部商品が Dealer Price ではない
- MAG 側 Cygnus Integration Kit が不足している
- 再見積依頼中

PHOTON 用 Integration Kit `7851-PHOTON` は Supplier Quote にあります。  
MAG 用 Integration Kit とは別物です。不足分を PHOTON 用 SKU で補完しないでください。

## Customer Quote の位置づけ

MAG / PHOTON の販売価格・送料は、当時実際に出した実績値です。

「なぜ 6,620,000 円なのか」「なぜ 1,190,000 円なのか」を、この STEP で新しい Rule として再計算しません。  
将来 Quote Engine の Policy が正式化されたとき、意図した差異なのか Engine のバグなのかを比較するための Expected Output です。

Customer Quote PDF に SKU が無い行へ、勝手に SKU を確定していません。  
Human Verified Mapping は `expected_validation.json` に分離しています。

## Shipping / Insurance / Lead Time

- Supplier Quote: Large Box ×3、Insurance 1,950 USD 別明細
- MAG Quote: Large Box ×2、保険料は販売価格内包
- PHOTON Quote: Large ×1 + Small ×1、保険料は販売価格内包

送料金額から Shipping Policy を逆算していません。

Lead Time（MAG 5か月程度 / PHOTON 3か月程度）は 2026-09-26 時点の Quote Snapshot です。  
Current Lead Time Master や恒久 TechnicalFact にはしません。

## 今回やっていないこと

- PDF 自動抽出
- Supplier Quote 価格の自動 Validation 本実装
- Pricing Policy / Landed Cost / 顧客見積生成
