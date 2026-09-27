# IHI-TECH-001-MR-001 Manufacturer Response Golden Case

表示名：IHI検査計測 MAG Utility Crawler Manufacturer Response Validation

## このGolden Caseの目的

初期相談で作ったメーカー確認テーマについて、Deep Trekkerから回答が返ったあと、次を正しく整理できるかを見る基準です。

- どの質問が回答済みか
- どの質問が部分回答か
- どの質問が未回答か
- 追加確認が必要か
- 質問外の追加情報は何か

「AIがそれらしい文章を書いたか」は評価しません。

今回は実AI評価は行いません。人間が確認した正しい到達状態だけを置いています。

## なぜ生のメーカー返信を置かないか

プロジェクト内のIHI整理情報は、メーカー確認後にSpaceOneが顧客向けへ整理した内容です。  
Deep Trekkerから届いた生メール本文そのものではありません。

そのため、次はしていません。

- 存在しないメーカー返信文を作ること
- Deep Trekkerのメール文面を捏造すること
- SpaceOneの顧客向け整理文を raw manufacturer response として扱うこと

`source_notes.json` の `source_type` は `HUMAN_VERIFIED_MANUFACTURER_RESPONSE_SUMMARY` です。  
`raw_response_available` は `false` です。

## 既存の初期Golden Caseとの関係

`ihi_tech_001/input.json` と初期の `expected.json` は変えていません。

- 初期相談時点：`ihi_tech_001/`
- メーカー回答後の到達状態：この `manufacturer_response/` フォルダ

2つの時点を混ぜないでください。

## PASS条件

将来メール本文を入れたときに PASS にする条件です。

- 11のメーカー確認テーマすべてに expected status がある
- 根拠がある質問だけ ANSWERED にする
- 根拠が弱い質問は PARTIAL、ない質問は FOLLOW_UP_REQUIRED のまま残す
- MAG は CUSTOMER_REQUESTED のまま
- PHOTON 案は MANUFACTURER_RECOMMENDED
- PHOTON を AI_SUGGESTED にしない
- 1輪 50 lb と、SpaceOneが足した約45kgfを混同しない
- 約45kgfをメーカー保証の保持力として TechnicalFact にしない

## FAIL条件

- 全質問を ANSWERED にする
- 位置把握の回答を、水深・テザー・方位・測定位置管理まで流用する
- 存在しない生メールを作る
- PHOTON を AI提案や顧客指定として扱う
- MAG をメーカー推奨へすり替える
- 確認前に TechnicalFact を確定する

## 実際のDeep Trekkerメールを取得したあと

1. 生メール本文を、このフォルダとは別に `input` として追加する
2. `raw_response_available` を true にする
3. Technical Case Agent のメーカー回答整理に、初期質問＋生メールを渡す
4. この `expected.json` の質問テーマと照合する
5. PASS / WARNING / FAIL を出す

生メールが来るまで、この expected は「人間確認済みの期待結果」として使います。
