# AGENTS.md — このリポジトリで作業する AI への約束

Kiro・Claude Code など、どの AI エージェントにも共通の約束。Kiro は常に読み込む。Kiro だけの補足は `.kiro/steering/` にある（中身は `docs/` の文書を読み込むだけ）。くわしい約束は `docs/conventions.md`、プロダクトと技術構成は `docs/overview.md`。

- 作成：2026-11-16（決勝に向けた追加開発の準備）
- 元にした資料：`README.md`、`backend/README.md`、`docs/design/rules.md`、`docs/adr/`

## このリポジトリは何か

**NurseNote**：病棟の看護師が、ベッドサイドの会話から根拠つきの看護記録（SOAP の S・O）の下書きを作り、確かめて確定するアプリ。DevFest GDGoC Japan Hackathon 2026（チーム t172）で決勝に進んだ。

- ここは**開発用リポジトリ**（非公開）。提出用リポジトリ（公開、`Devfest-Hackathon-2026/df-2026-t172`）には直接手を入れない
- 追加開発の期間は **11/18 12:00〜11/24 23:59**。計画と担当は `docs/planning/final-dev-plan.md`、手順は `docs/operations.md`

## 必ず守ること

1. **返事・文書・コメント・コミットメッセージの説明は日本語**。コード・識別子・コマンドは原文のまま
2. **決まりの一覧（`docs/design/rules.md`）に反することはしない**。場所が「B」の決まりはバックエンドのコードで強制し、テスト名に番号を入れる（例 `test_A05_...`）。画面（F）だけで守らせる決まりは作らない
3. **AI に判定させない**（[ADR-0001](docs/adr/0001-ai-role.md)）。診断・医療的な判断・依頼の優先順位・薬の名前と量を AI に書かせる変更は提案しない
4. **お金がかかる呼び出しと GCP の設定変更は、実行の前に Cさんの承認を取る**
   - お金がかかる：Gemini（Vertex AI）、Speech-to-Text、`MODE=live` での総合テスト（`--allow-paid`）
   - 設定変更：API の有効化、Cloud Run のデプロイ、Firestore・Secret Manager・IAM・予算の変更
   - 費用は単価・数量・小計の表で先に出す（`docs/conventions.md` の「お金がかかる呼び出しと GCP の設定変更」）
5. **秘密情報に触れない**：`.env`・鍵・合言葉・トークンは読まない、書かない、出力しない、コミットしない。合言葉は環境変数と Secret Manager だけ
6. **commit・push・ブランチの削除・履歴の書き換えは、頼まれたときだけ**
7. **データは架空だけ**（P-07）。実在の患者・病院・看護師の情報をコード・テスト・モックに入れない
8. **人の名前**：資料では Aさん（企画・進行）・Bさん（画面）・Cさん（バックエンド・DB・データ形式）と書く。本名・GitHub のユーザー名・メールアドレスは書かない
9. **他社の AI 製品の名前を、画面・資料・動画の台本に出さない**（H-01）。AI の利用記録には「対話型 AI」と書く

## 正しい情報がどこにあるか

食い違ったら、上の行を優先する。

| 何を | どこ |
|---|---|
| 守らせる決まり | `docs/design/rules.md` |
| API と Firestore の形（画面とバックエンドの契約） | `docs/design/data-model.md` |
| 速さ・費用・止まらないことの水準 | `docs/design/nonfunctional.md` |
| 認証と受け持ちの割り振り | `docs/design/auth.md` |
| 設計の考え方（叩き台、11/7 時点） | `docs/design/README.md` |
| 技術を選んだ理由 | `docs/adr/` |
| プロダクト（誰の、どんな困りごとか）と技術構成 | `docs/overview.md` |
| チームの約束・コードとテストの書き方・お金と GCP の承認 | `docs/conventions.md` |
| 起動・テスト・本番の設定 | `backend/README.md` |
| 開発の流れ・テスト・GCP・デプロイ・どこに何を書くか（決勝の追加開発） | `docs/operations.md` |
| なぜ作るか（現場の声） | `docs/research/hearing.md` |

## 変えるときの決まり

- API や保存の形を変えたら、`docs/design/data-model.md` を直して**末尾の変更履歴に1行**足す。画面（Bさん）に影響するので知らせる
- 決まりを足す・変えるときは `docs/design/rules.md` に番号つきで書き、変更履歴に残す。決めるのは人
- 技術や設計で迷ったら、決める前に ADR を書く（比べた案・選んだ理由・捨てた理由）
- 照合のコードを直したら、モックを作り直す（`python -m scripts.build_mocks`）
- AI に手伝ってもらったら、`docs/submission/ai-usage-log.md` に1行足す（なぜその場面で AI を使ったか、採らなかった提案も）

## テスト

変更の前と後に必ず回す。2026-11-16 時点で、バックエンド 311件・画面 121件がすべて通る。

```bash
cd backend
.venv/Scripts/python -m pytest -q
.venv/Scripts/ruff check . && .venv/Scripts/ruff format --check .
```

```bash
node --test frontend/tests/*.test.mjs
```

- テストは Gemini・Speech-to-Text・Firestore を差し替えて動かし、**実際には呼ばない**
- 画面の手元での確認は `MODE=mock` で起動する（`backend/README.md`）
