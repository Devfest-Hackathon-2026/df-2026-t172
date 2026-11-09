# NurseNote：ベッドサイドの会話から、根拠つきの看護記録の下書きを作る

病棟の看護師がベッドサイドで患者と話すと、その会話から看護記録（SOAP の S・O）の下書き・バイタル・患者の依頼を、**どの発言から来たか（根拠）つきで**作ります。AI が根拠なしに補った部分はコードの照合と AI の再確認で目立たせ、**看護師が1文ずつ確かめて確定**します。テーマ「Own the Why」に合わせ、AI を鵜呑みにせず、人が判断して記録に責任を持つ形にしました。

## 試す

- URL：https://nursing-draft-live-655696596429.asia-northeast1.run.app （Safari か Chrome で開いてください）
- 合言葉：提出物の Google Drive にあるプロダクト説明ドキュメントに書いてあります
- 使い方：[審査員向けの使い方](docs/submission/judges-guide.md)（5分ほど。名簿と会話はすべて架空です）

## 見てほしい資料

### 提出物（Google Drive）

| 資料 | 中身 |
|---|---|
| プロダクト説明ドキュメント | 誰の、どんな課題か、何を作ったか、なぜこの作りか、合言葉 |
| プレゼン動画（デモを含む） | 一連の流れを止めずに動かしたデモと、作った理由 |
| 著作物利用シート | 使ったライブラリ・素材とライセンス（リポジトリの [license-sheet.md](docs/submission/license-sheet.md) と同じ内容） |
| Google Cloud アーキテクチャ図 | 公式アイコンで描いた構成図（リポジトリの [architecture.md](docs/submission/architecture.md) が元） |

### リポジトリの中の資料

| 資料 | 何が分かるか |
|---|---|
| [AI の利用記録](docs/submission/ai-usage-log.md) | 開発で AI をどの場面で、なぜ使ったか。**採らなかった提案と、人が直したこと**も書いた |
| [審査員向けの使い方](docs/submission/judges-guide.md) | 5分で試す手順と、試す前に知っておいてほしいこと |
| [ヒアリング記録](docs/research/hearing.md) | 病棟の看護師に聞いた事実と、そこからチームが決めたこと（聞いた事実と解釈を分けて書いた） |
| [既存製品の調査](docs/research/existing-products.md) | 看護記録の AI の既存製品と、このプロダクトとの違い |
| [設計の判断の記録（ADR）](docs/adr/README.md) | テーマの選び方、AI に任せる範囲、Gemini と Vertex AI・Cloud Run を選んだ理由 |
| [構成](docs/submission/architecture.md) | Google Cloud の各サービスの使い方と、データの流れ |
| [守らせる決まり](docs/design/rules.md) | 安全・個人情報・費用の決まりと、それを確かめるテスト |
| [設計](docs/design/README.md)・[データの形](docs/design/data-model.md)・[利用シーン](docs/design/scenarios.md) | 画面と API の設計、デモで使う架空の場面 |

## 仕組み

```
録音（ブラウザ）─▶ Speech-to-Text（話者分離・時刻つき）─▶ 発言の列（番号はサーバーが振る）
                                                          │
                     Gemini ① 下書き（根拠の発言番号つき）◀┘
                          │
         コードの照合（根拠の実在・数・話者・薬の語・患者の取り違え）
                          │
         Gemini ② 再確認（各文が根拠の発言だけから言えるか）
                          │
         看護師が確かめて確定 ─▶ Firestore（記録・タスク。翌日0時以降に自動で消える）
```

| 部分 | 使ったもの |
|---|---|
| 実行 | Cloud Run（画面と API を1つのコンテナで配信、最大1インスタンス） |
| 下書きと再確認 | Vertex AI の Gemini（`gemini-3.5-flash`） |
| 文字起こし | Speech-to-Text V2（`chirp_3`、話者分離） |
| 保存 | Firestore（東京）。音声と会話の全文は保存しない |
| 秘密情報 | Secret Manager（API キーは使わず、サービスアカウントで認証） |
| バックエンド | Python・FastAPI（[backend/](backend/README.md)） |
| 画面 | HTML・CSS・JavaScript（[frontend/](frontend/)） |

詳しくは [構成](docs/submission/architecture.md)・[設計](docs/design/README.md)・[データの形](docs/design/data-model.md)・[守らせる決まり](docs/design/rules.md)・[設計の判断の記録](docs/adr/README.md)。

## 大事にしたこと

- **AI の出力は下書き**。確定するのは看護師で、根拠で裏付けられない文は「残す／消す」を選ぶまで確定できない
- **根拠の照合はコードで行う**（値・数・話者・薬の語・患者の取り違え）。AI の答えを AI だけで確かめない
- **診断・薬の名前と量・依頼の優先順位は AI に書かせない**。依頼の緊急度は、会話の手がかりからコードが決める
- **持たないデータは漏れない**：音声と会話の全文は保存せず、記録とタスクも翌日0時以降に消す。患者の名簿は電子カルテの持ち物なので、アプリでは登録・削除しない
- **患者の情報はアプリで持ち続けない**：名簿（名前・部屋・受け持ち）の持ち主は電子カルテ。本番では電子カルテから読み、アプリは自分の名簿を育てない。どう読むか（電子カルテの API・書き出したファイルの取り込みなど）は病院の仕組みに合わせて決める（未決）。今のデモは架空の名簿を起動時に入れているだけ。確定した記録とタスクには、カルテに貼る文のために名前と部屋番号の写しが入るが、翌日0時以降に消える
- **ログインなしで、依頼の担当を割り振れる**：患者ごとの受け持ちと、依頼ごとの担当（「担当に回す」「自分で引き取る」）をその日に変えられる。ログインがないので、変えた人・確定した人は画面で選んだ「自分」の**自己申告**として残す（本人の確かめはない。[決まり](docs/design/rules.md) S-08）

## 手元で動かす

```bash
cd backend
python -m venv .venv
.venv/Scripts/python -m pip install -r requirements-dev.txt   # Mac/Linux は .venv/bin/python
PASSCODE=12文字以上の合言葉 MODE=mock .venv/Scripts/python -m uvicorn --factory app.main:create_app --port 8080
```

`MODE=mock` では Gemini・Speech-to-Text・Firestore を一切呼ばず、利用シーンの見本で動きます。テストは `.venv/Scripts/python -m pytest -q`。詳しくは [backend/README.md](backend/README.md)。

## 今回入れなかったこと（今後の拡張）

- ログインと「誰が確定したか」「誰が担当・受け持ちを変えたか」の記録（[認証・認可の設計](docs/design/auth.md)）
- 電子カルテの患者一覧・受け持ち表とのつなぎ込み（取り方は未決。アプリでは患者の情報を持ち続けない）
- 依頼のラベル（中身の種類・職種）を、現場の看護師の意見に合わせて直す

## ライセンス

[MIT](LICENSE)。使ったライブラリとライセンスは [著作物利用シート](docs/submission/license-sheet.md)。
