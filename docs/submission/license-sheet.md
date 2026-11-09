# 著作物利用シート（下書き）

プロダクトで使った素材・ライブラリ・データの出典とライセンスを、使うたびに1行足す。運営の様式が届いたら写す。

| 種類 | 名前 | 出典（URL） | ライセンス | 使い方 | 確認した人 |
|---|---|---|---|---|---|
| ライブラリ | FastAPI 0.162.1 | https://github.com/fastapi/fastapi | MIT | API サーバー | Cさん（11/8、入っているパッケージの情報で確認） |
| ライブラリ | Uvicorn 0.54.0 | https://github.com/encode/uvicorn | BSD-3-Clause | API サーバーの起動 | Cさん（11/8、入っているパッケージの情報で確認） |
| ライブラリ | Pydantic 2.14.3 | https://github.com/pydantic/pydantic | MIT | 入出力の形の検証 | Cさん（11/8、入っているパッケージの情報で確認） |
| ライブラリ | python-multipart 0.0.33 | https://github.com/Kludex/python-multipart | Apache-2.0 | 音声のアップロードの受け取り | Cさん（11/8、入っているパッケージの情報で確認） |
| ライブラリ | Google Gen AI SDK（google-genai 3.0.0） | https://github.com/googleapis/python-genai | Apache-2.0 | Gemini（Vertex AI）の呼び出し | Cさん（11/8、入っているパッケージの情報で確認） |
| ライブラリ | google-cloud-speech 2.41.0 | https://github.com/googleapis/google-cloud-python | Apache-2.0 | Speech-to-Text V2 の呼び出し | Cさん（11/8、入っているパッケージの情報で確認） |
| ライブラリ | google-cloud-firestore 2.34.1 | https://github.com/googleapis/python-firestore | Apache-2.0 | Firestore への保存 | Cさん（11/8、入っているパッケージの情報で確認） |
| ライブラリ（開発のみ） | pytest 9.2.0・httpx 0.28.1・ruff 0.17.4 | https://pytest.org/ ・ https://www.python-httpx.org/ ・ https://docs.astral.sh/ruff/ | MIT・BSD-3-Clause・MIT | テスト・検査（本番のコンテナには入れない） | Cさん（11/8、入っているパッケージの情報で確認） |
| ソフトウェア | FFmpeg（Debian のパッケージ） | https://ffmpeg.org/ | LGPL-2.1 以降（ビルドの設定により GPL。Debian の版は要確認） | コンテナの中で音声を FLAC に変換する外部のプログラムとして呼ぶ。リポジトリには含めない | Cさん（11/8、入っているパッケージの情報で確認） |
| ソフトウェア | Python 3.12（公式の Docker イメージ `python:3.12-slim`） | https://hub.docker.com/_/python | PSF License（イメージの中の Debian の各パッケージはそれぞれのライセンス） | 実行環境 | Cさん（11/8、入っているパッケージの情報で確認） |
| ライブラリ | （例）@material/web | https://github.com/material-components/material-web | Apache-2.0 | 画面の部品 | |
| フォント | （例）Roboto、Noto Sans JP | https://fonts.google.com/ | SIL Open Font License 1.1 | 画面の文字 | |
| アイコン | （例）Material Symbols | https://fonts.google.com/icons | Apache-2.0 | 画面のアイコン | |
| アイコン | （例）Google Cloud 公式アイコン | https://cloud.google.com/icons | 利用規約を確認 | アーキテクチャ図 | |
| データ | （例）自治体の公開様式 | | 利用条件を確認 | デモのサンプル | |
| 統計 | （例）厚労省などの統計 | | 出典明記で利用可か確認 | 説明資料の根拠 | |

（例）の行は、実際に使ったら「（例）」を消して残す。使わなかったら消す。

## 注意

- デモで使う写真・書類は、架空のものか、利用条件を確かめた公開資料だけにする。実在の人の写真や書類は使わない
- 生成 AI で作った画像を使う場合は、その旨と使ったモデルを書く
