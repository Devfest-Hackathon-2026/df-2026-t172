# バックエンド

看護記録の下書きアプリの API（FastAPI）。画面（`frontend/`、Bさん）も同じアプリから配信する。API と Firestore の形は [データの形](../docs/design/data-model.md) が契約で、守らせる決まりは [決まりの一覧](../docs/design/rules.md)（場所が B の決まりはすべてここのコードで強制し、テスト名に番号を入れている。例 `test_A05_...`）。

## 起動（モック：Gemini・Speech-to-Text・Firestore を一切呼ばない）

```bash
cd backend
python -m venv .venv
.venv/Scripts/python -m pip install -r requirements-dev.txt   # Mac/Linux は .venv/bin/python
```

```bash
PASSCODE=好きな合言葉 MODE=mock .venv/Scripts/python -m uvicorn --factory app.main:create_app --reload --port 8080
```

- 画面は http://localhost:8080/ （`frontend/index.html` を置くと出る）、API は `/api/...`
- すべての API でヘッダー `X-Passcode` に合言葉を入れる（違えば 401）。`/healthz` だけは合言葉なし
- `PASSCODE` がないと起動しない（合言葉はコードに書かない）

モックで返すもの：

| API | 動き |
|---|---|
| `GET /api/patients` | `seed/patients.json`（架空の名簿6人） |
| `POST /api/drafts` | 音声は `consent_confirmed=true` が要る（O-01、なければ 400）。選んだ患者に応じて `mock/draft_s*.json`（302→場面1、305→場面2、308→場面3、310→場面4、312→場面5、ほか→場面1）。患者の照合だけは選んだ患者でやり直す（303 を選ぶと赤） |
| `POST /api/verify` | コードの照合は本物と同じ。`entail: true` の二段目は見本の判定を返し、直した文は「判断できない」になる |
| `POST /api/records`・タスク | メモリに保存（再起動で消える）。タスクには3段の見本が最初から入っている（`mock/tasks.json`） |

画面だけを先に作るときは、バックエンドを動かさずに `mock/draft_s1.json`〜`draft_s5.json` を直接読んでもよい。

## テスト・検査

```bash
.venv/Scripts/python -m pytest -q
.venv/Scripts/ruff check . && .venv/Scripts/ruff format --check .
```

- spike の46件（`tests/test_layers.py`・`test_layers_match.py`・`test_edges.py`）と、批判の記録 3回目の4〜8の直し（`test_fixes.py`）、API（`test_api_mock.py`・`test_api_live.py`）、live の接続コード（`test_live_clients.py`）
- live のテストは Gemini・Speech-to-Text・Firestore を差し替えて動かす。**実際には呼ばない**
- 照合を直したら `python -m scripts.build_mocks` でモック JSON を作り直す（`test_mock_files.py` が古いモックを見つける）

### 総合テスト（デプロイしたものを外から通しで確かめる）

提出の直前と、デプロイのたびに回す。画面から API を呼ぶ順の見本にもなる（`scripts/smoke_flow.py`）。

```bash
SMOKE_PASSCODE=合言葉 .venv/Scripts/python -m scripts.smoke_test --url https://nursing-draft-655696596429.asia-northeast1.run.app
```

- 合言葉は環境変数 `SMOKE_PASSCODE` だけから読む（引数・出力に出さない）。値はコンソールの Secret Manager で見る（下の「合言葉と署名の鍵」）
- 流れ：health（mode を表示）→ 合言葉なしで 401 → `/docs` などが 404 → 名簿（部屋番号の順・`assigned_to`）→ 下書き（場面1の会話をテキストで）→ 照合（`entail=false`、数字を変えて `number_not_in_evidence`）→ 照合（`entail=true`）→ 確定（署名を返し、`confirm_id` つき）→ タスク（`patient_words`・済みにする）→ 音声で同意がないと 400 → テキスト5,001字で 413
- 1行ずつ `OK`／`NG`／`--`（飛ばした）を出し、終了コードは NG の数（0 なら全部 OK）
- **live の URL では、下書きと `entail=true` が Gemini を呼ぶ（お金がかかる）**。`--allow-paid` を付けたときだけ回し、付けなければ飛ばす。mock は全部回す
- live で確定まで回すと、記録とタスクが Firestore に残る（翌日0時以降に TTL で消える）。最後にその旨を出す
- 手元で試すとき：`PASSCODE=12文字以上の合言葉 MODE=mock` でサーバーを起動し、`--url http://localhost:8080`

## 本番（MODE=live）

**お金がかかる呼び出しと GCP の設定変更は、実行の前にCさんが承認する。**

| 環境変数 | 既定 | 中身 |
|---|---|---|
| `MODE` | `mock` | `mock` / `live` |
| `PASSCODE` | （必須） | 合言葉。Cloud Run では Secret Manager から渡す |
| `GOOGLE_CLOUD_PROJECT` | `df-2026-t172` | |
| `GEMINI_LOCATION` / `GEMINI_MODEL` | `global` / `gemini-3.5-flash` | 東京では従量課金で使えないため `global`（P-05 の例外、ADR-0004）。思考は `thinking_level=MINIMAL`。思考トークンが出たら警告し、費用に足してログに出す。単価を確かめていないモデルは起動時にはじく |
| `SPEECH_LOCATION` / `SPEECH_MODEL` | `us` / `chirp_3` | 日本語の話者分離は東京では使えない（11/8 の技術検証、P-05 の例外）。同期の認識は60秒までなので、55秒ずつ5秒重ねて区切って続けて送る |
| `FIRESTORE_DATABASE` | `(default)` | 場所は `asia-northeast1`。`records`・`tasks` の `expires_at` に TTL を設定する |
| `DAILY_CALL_LIMIT` | `300` | 有料の呼び出しの1日の上限（C-04。下書き1回＝テキスト2・音声3と数える）。メモリで数える |
| `MAX_AUDIO_BYTES` / `MAX_AUDIO_SECONDS` / `MAX_TRANSCRIPT_CHARS` | 10MB / 180 / 5000 | 入力の上限（SEC-04、超えたら 413） |

- 認証は Cloud Run のサービスアカウント（鍵ファイルは使わない。11/14 まで認証の更新なしで動く）
- **音声と会話の全文は保存しない**。Firestore に入るのは確定した記録とタスクだけで、記録には残った要素の根拠になった発言だけを一緒に入れる（P-01・P-02）
- 計測用の時刻と Gemini の使用量は、標準出力に JSON 1行で出す（Cloud Logging で拾う）。ログに会話の文・患者名・例外の本文は出さない（P-04、`app/services/safe_log.py`）
- 認証の確認は `app/auth.py` の1か所（今は合言葉だけ。11/9 に受け持ちの割り振りを足すときはここで看護師を特定する、S-08）
- Cloud Run 用のイメージはリポジトリ直下の `Dockerfile`（最大1インスタンスで動かす前提）

### 合言葉と署名の鍵（Secret Manager。2026-11-08 に設定済み）

| サービス | 環境変数 | シークレット（バージョン） |
|---|---|---|
| `nursing-draft`（mock） | `PASSCODE` | `passcode-mock`（1） |
| `nursing-draft-live`（live） | `PASSCODE` | `passcode-live`（1） |
| `nursing-draft-live`（live） | `ENTAIL_SEAL_KEY` | `entail-seal-key-live`（1） |

- 場所は `asia-northeast1` だけ（`--replication-policy=user-managed --locations=asia-northeast1`）
- 読めるのは実行用のサービスアカウント `cloud-run-vertex-sa` だけで、`roles/secretmanager.secretAccessor` は**この3つのシークレットにだけ**付けている（プロジェクト全体には付けない）
- **バージョンは番号で固定する（`latest` にしない）**。提出後に誰かが新しいバージョンを足したり古いものを無効にしたりしても、動いているサービスが起動できなくなるのを防ぐため。値を変えるときは、新しいバージョンを足してから `--update-secrets PASSCODE=passcode-live:2` のように番号を上げる
- 値の見方：コンソールの「Secret Manager」→ シークレットを選ぶ →「バージョン」の行の「︙」→「シークレットの値を表示」。コマンドなら `gcloud secrets versions access 1 --secret passcode-mock $A`（画面に出るので、人に見せる場では使わない）
- mock の `nursing-draft` には `ENTAIL_SEAL_KEY` を入れていない。起動のたびに鍵が変わるので、0台から起動し直す前に作った下書きは、確定のときに二段目を呼び直す（mock なので費用はかからない）
- 費用：無料枠（請求先アカウントごとに月あたり、アクティブなバージョン6つ・アクセス1万回）に収まる。アクセスはインスタンスの起動のたびに数回だけ

切り替えたときの手順（イメージは作り直さない。`A="--account <アカウント> --project df-2026-t172"`）：

```bash
# 値は describe の結果からパイプで渡し、画面にもファイルにも出さない
gcloud secrets create passcode-mock --replication-policy=user-managed --locations=asia-northeast1 --data-file=- $A
gcloud secrets add-iam-policy-binding passcode-mock --member=serviceAccount:cloud-run-vertex-sa@df-2026-t172.iam.gserviceaccount.com --role=roles/secretmanager.secretAccessor $A
gcloud run services update nursing-draft --region asia-northeast1 --remove-env-vars PASSCODE --update-secrets PASSCODE=passcode-mock:1 $A
gcloud run services update nursing-draft-live --region asia-northeast1 --remove-env-vars PASSCODE,ENTAIL_SEAL_KEY --update-secrets PASSCODE=passcode-live:1,ENTAIL_SEAL_KEY=entail-seal-key-live:1 $A
```

### Firestore の用意（2026-11-08 に設定済み。提出後は変えられない）

| 項目 | 設定 | 決まり |
|---|---|---|
| データベース | `(default)`・ネイティブモード・`asia-northeast1`（場所は作った後に変えられない）。無料枠の対象 | P-05 |
| TTL | `records.expires_at`・`tasks.expires_at`（値は作った日の翌日0時 JST）。消えるのは期限から最大24時間ほど後で、それまでの間はコードが期限切れを返さない | P-03 |
| セキュリティルール | リポジトリ直下の `firestore.rules`（クライアントの読み書きはすべて拒否）。サーバーはサービスアカウント `cloud-run-vertex-sa`（`roles/datastore.user`）で読み書きし、ルールの対象外 | SEC-02 |
| インデックス | 単一フィールドの自動インデックスだけ（複合インデックスは使わない、`app/store/firestore_store.py`） | |

作ったときの手順（同じプロジェクトでもう一度実行する必要はない。`A="--account <アカウント> --project df-2026-t172"`）：

```bash
gcloud services enable firestore.googleapis.com firebaserules.googleapis.com $A
gcloud firestore databases create --database="(default)" --location=asia-northeast1 --type=firestore-native $A
gcloud firestore fields ttls update expires_at --collection-group=records --enable-ttl --async $A
gcloud firestore fields ttls update expires_at --collection-group=tasks --enable-ttl --async $A
```

ルールは firebase CLI を使わず、Firebase Rules API で置いた：`POST https://firebaserules.googleapis.com/v1/projects/df-2026-t172/rulesets` に `firestore.rules` の中身を送ってルールセットを作り、`POST .../releases` で `projects/df-2026-t172/releases/cloud.firestore` をそのルールセットに向けた（アクセストークンは `gcloud auth print-access-token`、ヘッダー `x-goog-user-project: df-2026-t172`）。`firestore.rules` を変えたら、ルールセットを作り直し、release を `PATCH` で付け替える。

確かめ方（読み取りだけ）：

```bash
gcloud firestore databases describe --database="(default)" $A   # locationId: asia-northeast1、type: FIRESTORE_NATIVE
gcloud firestore fields ttls list $A                             # records と tasks の expires_at が state: ACTIVE
```

- ルール：`GET https://firebaserules.googleapis.com/v1/projects/df-2026-t172/releases` の `cloud.firestore` が指すルールセットの中身が `firestore.rules` と同じであること。`POST .../projects/df-2026-t172:test` に、`records`・`tasks`・`patients` への get・list・create・update・delete を、ログインあり・なしで `expectation: DENY` として送り、30件すべてが `SUCCESS` になること（11/8 に確認済み）
- 保存先：手元で `MODE=live` の設定と `FirestoreStore.connect`、差し替えの Gemini（`MockGemini(scenarios, "s1")`）を組み合わせ、Gemini を呼ばずに API を通した（11/8）。結果は、名簿の投入（6件）、`GET /api/patients`、`POST /api/records`（記録1件・タスク1件。`expires_at` は Firestore の日時型で、会話の全文は入らない）、`GET /api/tasks`・`?status=done`、`PATCH /api/tasks/{id}`（緊急度・済み）、同じ `confirm_id` での送り直し（上書き・前のタスクは消える）がすべて通った。試しに入れた記録とタスクは消し、名簿だけを残している

## ファイル

| 場所 | 中身 |
|---|---|
| `app/checks/` | 照合（コード）：数の読み替え、バイタルの取り出し、文の照合、患者の照合、二段目の入出力 |
| `app/services/` | 下書きを作る流れ、SOAP への振り分けと緊急度、確定、カルテ用の文 |
| `app/live/` | Gemini（Vertex AI）・Speech-to-Text V2 の呼び口と、モックの差し替え |
| `app/store/` | 保存先（メモリ・Firestore） |
| `app/routes/` | API |
| `mock/` | 画面向けのモック JSON と、その元データ（`mock/source/scenarios.json`） |
| `seed/patients.json` | 架空の名簿 |
