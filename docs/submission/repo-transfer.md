# 提出用リポジトリへの移し方

[ADR-0005](../adr/0005-dev-and-submission-repos.md) で、非公開の開発用リポジトリ（`Yuranosuke311/df26-t172-dev`）で開発し、最終版だけを**公開**の提出用リポジトリ（`Devfest-Hackathon-2026/df-2026-t172`）へ移すと決めた。ここではその手順と、移す前の確かめ方をまとめる。**まだ移していない**。11/9 に手元で予行した（書き出した中身だけでバックエンドのテスト 281件が通り、秘密の値・メールアドレスがないことを確かめた）。本番は 11/10 12:00 の最後のデプロイの後に行う。

守ること：

- **履歴を持ち込まない**（過去のコミットに秘密情報が残っていると、公開されるため。SEC-06）
- **秘密情報を入れない**（`.env`、鍵、合言葉の値。SEC-06）
- **開発開始（11/5 10:00）より前に書いたコードを入れない**（H-04）

## 1. 移すもの・移さないもの

| 移す | 移さない |
|---|---|
| `backend/`（`.venv/`・キャッシュは除く。Git に入っていないので下の手順なら自然に除かれる） | `.env` などの秘密情報（そもそも Git に入れていない） |
| `frontend/` | `docs/submission/pre-submit-checklist.md`（アカウント名が入っている） |
| `Dockerfile`・`.dockerignore`・`.gitignore`・`firestore.rules` | `spike/`（技術検証のコード。11/9 決定：移さない） |
| `docs/adr/`・`docs/design/` | （`docs/research/` は 11/9 に移すことに変更。ヒアリングの記録は相手の名前・病院名がないことを読み直して確かめた。既存製品の調査も、他社の製品名を出さない決まり（H-01）は「プロダクトで Google 以外の製品を使わない」の意味なので、資料として載せてよいと判断） |
| `docs/submission/` のうち審査に役立つもの（`architecture.md`・`judges-guide.md`・`ai-usage-log.md` など） | `docs/submission/judging-map.md`・`docs/schedule.md`（内部の作業メモに近い。11/9 決定：移さない） |
| 提出用の `README.md`（[submission-readme.md](submission-readme.md) を置き換える。運営のひな形の README は上書きする）。`.gitignore` は運営のものに開発用のものを足す | |
| `LICENSE` は**提出用リポジトリにある運営の MIT（著作権者「The contributors of this repository」）をそのまま使う**。開発用の `LICENSE` は移さない | |

## 2. 移す前の確かめ方

開発用リポジトリの手元で、移す直前のコミットに対して行う。

### 秘密情報が入っていない（SEC-06）

```bash
# Git に入っているファイルの一覧に、秘密情報らしい名前がないこと（何も出なければよい）
git ls-files | grep -Ei '\.env|\.pem$|\.key$|-key\.json$|service-account|credentials'

# 中身に、鍵や合言葉らしい文字列がないこと（出たら1件ずつ人が見る）
git grep -nIE 'BEGIN (RSA |EC )?PRIVATE KEY|"private_key"|AIza[0-9A-Za-z_-]{20,}|PASSCODE=[^ <.…$]'

# 個人のメールアドレスが入っていないこと（出たら移さないか、消す）
git grep -nIE '[A-Za-z0-9._%+-]+@(gmail|yahoo|outlook|icloud)\.com'
```

- 合言葉の値は、**提出物の Google Drive にあるプロダクト説明ドキュメントにだけ**書く。公開の GitHub（コード・README・審査員向けの使い方）には書かない（11/9 決定）
- 合言葉と署名の鍵の値は Secret Manager にあり、リポジトリには入っていない（[backend/README.md](../../backend/README.md)）

### 開発開始より前のコードがない（H-04）

```bash
# ファイルごとに、最初に Git に入った日時（いちばん古いものが 2026-11-05 10:00 以降であること）
git log --diff-filter=A --format="%ad" --date=iso | sort | head -1
```

- 開発用リポジトリの最初のコミットは 2026-11-05 23:41（文書だけ）。コードを含む `spike/`・`backend/` の最初の追加は 2026-11-07 だった（この文書を書いた時点）
- Git の日時で分かるのは「いつ入れたか」だけで、「いつ書いたか」ではない。**よそから持ってきたコードがないことは人が確かめる**（チームの3人に聞く）

### 移したものだけで動く

- 提出用リポジトリの中身だけで、`backend/README.md` の手順どおりに mock で起動し、テストが通ること（ADR-0005「移したあと、提出用リポジトリの中身で起動できるか確かめる」）

## 3. 手順

履歴を持ち込まないため、`git push` で枝を送るのではなく、**ファイルだけを書き出して**提出用リポジトリに1つのコミットとして入れる。

```bash
# 1. 開発用リポジトリの、移す時点のコミットからファイルだけを書き出す（Git に入っていないものは出ない）
cd df26-t172-dev
git archive --format=tar HEAD -o ../export.tar

# 2. 提出用リポジトリを別の場所に用意する（開発用リポジトリの中には置かない）
cd ..
git clone https://github.com/Devfest-Hackathon-2026/df-2026-t172.git
cd df-2026-t172

# 3. 書き出したファイルを展開し、移さないものを消す
tar -xf ../export.tar
rm -rf spike docs/schedule.md LICENSE \n       docs/submission/pre-submit-checklist.md docs/submission/judging-map.md
git checkout LICENSE                            # 運営の LICENSE に戻す
cp docs/submission/submission-readme.md README.md && rm docs/submission/submission-readme.md

# 4. 提出用の README を書き、2章の確かめ方をこのフォルダでもう一度行う

# 5. 1つのコミットにして送る
git add -A
git status          # 入るものを人が目で見る
git commit -m "feat: 提出版"
git push
```

- 手順 5 の `git push` は公開リポジトリへの送信なので、**送る前にチームで中身を見てから**行う
- 11/9 の練習では手順 4 まで行い、送らない（送ると公開される）。【未決】練習で一度送ってよいか（送ったものは後のコミットで消しても、履歴に残る）
- 締切の後、提出用リポジトリは読み取り専用になる。送り忘れたものは審査されない

## 4. 送った後

- 提出用リポジトリの README に、デプロイした URL（live）が書いてあること（[提出物チェックリスト](README.md)）
- GitHub の画面で、公開されたファイルの一覧に 1章の「移さない」ものがないこと
