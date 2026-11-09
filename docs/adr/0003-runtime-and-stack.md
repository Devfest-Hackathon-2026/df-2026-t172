# 0003. 実行基盤と技術構成

- 状態：**決定**（11/7 の打ち合わせ。実行基盤 A・言語 A に、保存先 Firestore を足した）
- 日付：2026-11-05（11/7 に背景と確認事項を更新、決定）
- 決めた人：11/7 の打ち合わせ
- 提案した人：Cさん

## 背景

- アプリの実行に、App Engine・Compute Engine・GKE・Cloud Run・Firebase App Hosting・Firebase Hosting のどれか1つ以上が必須（キックオフ資料）
- 開発は6日間（11/5〜11/10）。11/6 から3人（Cさん・Aさん・Bさん）
- 作るものは看護記録の支援に決まった（[ADR-0006](0006-theme-nursing-record.md)）。「音声を受け取る → 文字起こし → Gemini で項目・下書き・依頼に整理 → 根拠付きで表示 → 看護師が確定」の流れ。画面は数枚で済む
- 音声の文字起こしと話者分離（看護師と患者の声を分ける）に Speech-to-Text を使うか、Gemini に音声を直接渡すかも決める必要がある
- 審査の配点は完成度が9点で最大。1本の流れを最後まで動かすことが最優先

## 比べた案（実行基盤）

| 案 | 利点 | 欠点 |
|---|---|---|
| A. Cloud Run（コンテナ1つで画面と API を配信） | 言語を選ばない。サービスアカウントで Vertex AI を呼べる。無料枠が大きい | Dockerfile が必要 |
| B. Firebase Hosting（画面）＋ Cloud Run（API） | 画面の配信が速い。Firebase Auth などと組み合わせやすい | 2か所にデプロイする必要がある |
| C. App Engine | 設定が少ない | 新しく使う人が少なく、情報が古いことがある |
| D. Firebase App Hosting（Next.js など） | フロント中心なら速い | Next.js などに縛られる |

## 比べた案（言語・フレームワーク）

| 案 | 利点 | 欠点 |
|---|---|---|
| A. Python + FastAPI、画面は HTML + 素の JavaScript | Cさんが慣れている。Gemini の Python SDK が充実。ビルドが要らない | 画面が複雑になると書きにくい |
| B. TypeScript + Next.js | 画面を作り込みやすい | 3人とも慣れていなければ立ち上げに時間がかかる |
| C. Flutter（Web） | Google 技術として見せやすい。スマホでも動く | 慣れていないと6日では厳しい |

画面の部品は、どの案でも Material Design 3 の公式実装（`@material/web` など）と、Google 公式の色計算ライブラリ（`material-color-utilities`）を使う想定。

## 提案

実行基盤は **A（Cloud Run）**、言語は **A（Python + FastAPI、画面は HTML + 素の JavaScript）**。Bさんは HTML・CSS・JavaScript・PHP に最も慣れていて、大学で Python を学んでいる（11/6 の自己紹介）。画面を素の HTML・JavaScript にすれば、Bさんが慣れた技術で画面を担当できる。

## 決めたこと（11/7）

- 実行基盤：Cloud Run（東京、最大1インスタンス）。FastAPI が API と画面（`frontend/`）を1つのコンテナで配信する（リポジトリ直下の `Dockerfile`）
- 言語：Python + FastAPI、画面は HTML + 素の JavaScript
- 保存先：**Firestore**（`asia-northeast1`）。確定した記録とタスクだけを保存し、TTL で翌日0時以降に消す。音声と会話の全文は保存しない（[データの形](../design/data-model.md)、[決まりの一覧](../design/rules.md) P-01〜03）。最初の案は「サーバーは状態を持たず、記録はブラウザ内」だったが、打ち合わせで Firestore に変えた。理由：Google Cloud の IAM でアクセスを制御でき（読み書きは Cloud Run のサービスアカウントだけに許す）、Cloud Run・Vertex AI など他の Google Cloud の製品とまとめて管理しやすいため
- 文字起こしの方法（Speech-to-Text か、Gemini に音声を直接渡すか）は、今は Speech-to-Text で作っている。日本語の話者分離は未検証

## 決める前に確認すること

- [x] 他のメンバーの得意な言語・フレームワーク（Bさん：HTML・CSS・JavaScript・PHP。Aさん：企画・設計と進行が中心）
- [ ] 3人とも同じ Google Cloud プロジェクトの権限を持てるか（ハッカソン用プロジェクトの ID も確認する）
- [ ] 画面をスマホで使う前提か（看護師が持ち歩く端末を確認中。[ヒアリング記録](../research/hearing.md)）
- [ ] 文字起こしを Speech-to-Text で行うか、Gemini に音声を直接渡すか（技術検証で決める）

## AI の使い方

比べる案の洗い出しは AIに手伝わせた。どれを選ぶかは、チームの得意分野を聞いてから人が決める。
