# Implementation Plan

## 概要
Aさんが 11/19 21:00 から画面を作れるように、データの形・名簿seed・作り直した見本を最初に push する。次に看護計画の処理（`services/care_plan.py`・`chart.py`・ルート・起動時の確かめ）を作り、Bさんが 11/19 20:00 から触る `services/confirm.py`・`store/firestore_store.py` をその前に push する。文書（rules.md・data-model.md）は 11/19 中に直し、最後に全テストを回す。デプロイは Cさんの承認の前で止まる。
テストはどれも `pytest.mark.parametrize` の例の表で書き（Hypothesis などのライブラリは足さない）、Gemini は `MockGemini`・`FakeGemini`、Speech-to-Text は `FakeSpeech`、Firestore は `FakeFirestore` に差し替え、本物を呼ばない。

## Tasks

- [x] 1. Aさんへの引き渡し（データの形・名簿seed・見本。11/19 21:00 より前に push）
  - [x] 1.1 `plan_id` の形のテストを書く（落ちることを確かめる）
    - `backend/tests/test_care_plan_models.py`（新規）に `test_R03_plan_id_form`（性質2）。注 `# Feature: care-plan-soap, Property 2: plan_id の形` を付ける
    - 通る例：`null`・欄なし（`None` になる）・`cp01`・40字。わざと壊した例：空の文字列・41字・`cp 01`・`cp/01`・`5`・`1.5`・`true`・`[]`・`{}` で `ValidationError`、場所が `plan_id` の1件だけ
    - _Requirements: 3.1, 3.2, 3.3_
  - [x] 1.2 データの形を作る（1.1 を通す）
    - `models/limits.py`：`MAX_CARE_PLANS = 10`・`MAX_CARE_PLAN_LABEL_CHARS = 100`
    - `models/care_plan.py`（新規）：`_one_line_label`・`CarePlanLabel`・`CarePlan`・`_none_as_empty`・`_unique_in_patient`・`CarePlans`。例外の文に `label` の値を入れない
    - `models/api.py`：`Patient` の最後に `care_plans: CarePlans = Field(default_factory=list, ...)`。`PatientAssigneePatch` は変えない
    - `models/draft.py`：`SoapSentence.plan_id: SafeId | None = None`。`Vital`・`PatientRequest`・`EvidencedText` は変えない
    - _Requirements: 1.5, 1.7, 2.2, 2.7, 3.1, 3.2, 3.3, 3.8_
  - [x] 1.3 名簿seed のテストを書く（落ちることを確かめる）
    - `tests/test_care_plan_models.py` に `test_P07_seed_care_plans_shape`（生の JSON で6人全員に `care_plans`、各要素のキーが `{"id", "label"}`、1件以上、`id` が `^cp\d{2}$` で名簿全体で重ならない）
    - `test_P07_seed_care_plan_labels_distinct`（前後の空白なし、「計画外」でない、患者の中で NFKC と前後の空白を除いた形が重ならない）。わざと壊した例：前後に空白のある `label`、「計画外」、「#急性疼痛」と「＃急性疼痛」を入れた名簿を判定の関数に渡して落ちる
    - `test_S08_seed_p305_has_acute_pain`（p305 に `{"id": "cp04", "label": "#急性疼痛"}` がちょうど1件）
    - `test_S08_seed_other_fields_unchanged`（`care_plans` を除いた6人の欄の値と部屋番号の順。期待値は直す前の `backend/seed/patients.json` から写してテストに書く）
    - _Requirements: 1.1, 1.2, 1.3, 1.4, 1.8, 1.10_
  - [x] 1.4 名簿seed に看護計画を入れる（1.3 を通す）
    - `backend/seed/patients.json` の6人に design「Data Models」の「名簿seed の看護計画の案」の表のとおり `cp01`〜`cp08` を入れる（p302 `cp01`・`cp02`、p303 `cp03`、p305 `cp04`・`cp05`、p308 `cp06`、p310 `cp07`、p312 `cp08`）
    - `#` は半角。人数・並び・`care_plans` 以外の欄は変えない
    - _Requirements: 1.1, 1.2, 1.3, 1.4, 1.5, 1.6, 1.7, 1.8, 1.10_
  - [x] 1.5 今のテストを直し、見本を作り直す
    - 先にテストを直して落ちることを確かめる：`tests/test_api_mock.py` の名簿の1件目の期待値に `care_plans` を足す。`tests/test_mock_files.py` の `test_mock_file_matches_contract` に「S・O のすべての `plan_id` が `null`」「`patient.care_plans` が名簿seed と同じ」を足す（5場面）
    - `backend` で `python -m scripts.build_mocks` を回し、`backend/mock/draft_s1.json`〜`draft_s5.json` を作り直す（手で書かない）。`test_mock_file_is_up_to_date` が通ることを確かめる
    - 見本を読む画面のテストのため `node --test frontend/tests/*.test.mjs` も回す
    - _Requirements: 2.1, 2.3, 4.1, 4.3, 10.5_
  - [x] 1.6 commit・push し、Aさんに知らせる
    - `cd backend && .venv/Scripts/python -m pytest -q && .venv/Scripts/ruff check . && .venv/Scripts/ruff format --check .` を通してから、モデル・名簿seed・見本・テストを commit・push
    - Aさんに design の「画面（Aさん）に渡すデータの形」の節を送る（画面の看護計画の選択肢は名簿API・下書きAPI の `care_plans` からだけ作る）
    - _Requirements: 2.8, 5.1_

- [x] 2. 看護計画の処理
  - [x] 2.1 印を消す・確かめ・ログの数のテストを書く（落ちることを確かめる）
    - `tests/test_care_plan_logic.py`（新規）に、性質の注を付けて次の表を書く
    - `test_A14_clear_plan_ids`（性質3）：5場面の見本の S・O に `plan_id` を書き込んだもの（s4 を含む）。すべて `None`、ほかの欄と元の下書きは変わらない
    - `test_R03_unknown_plan_paths`（性質5）：p305 の下書きに `cp04`・`None`・`cp01`・`cp99`・`CP04`、看護師が足した文にだけ `cp02`。`ensure_known_care_plans` の `message` は1件・S と O に1件ずつ・7件（「ほか2件」）の3例で、「S 1文目」の書き方があり、`label` と送った値がない
    - `test_P04_confirm_log_plan_counts`（性質9）：文なし、全部計画外、S と O に別の計画、同じ計画に2文、空白だけの文にだけ付いた計画（`plans_used` に数えない）、計画のない患者
    - _Requirements: 4.1, 4.3, 6.1, 6.2, 9.1, 9.2, 9.3_
  - [x] 2.2 `services/care_plan.py` を作る（2.1 を通す）
    - 新規：`UNPLANNED_HEADING`・`PlanSection`・`clear_plan_ids`・`unknown_plan_paths`・`ensure_known_care_plans`（`record_rejected` のログは数だけ、`ApiError(422, "unknown_care_plan", ...)`）・`sentence_label`・`plan_log_fields`
    - 外の部品（Gemini・Speech-to-Text・Firestore）を import しない
    - _Requirements: 4.1, 6.1, 6.2, 9.1, 9.2, 9.3, 9.4, 9.5, 10.4_
  - [x] 2.3 カルテ用の文のテストを書く（落ちることを確かめる）
    - `tests/test_care_plan_chart.py`（新規）に、**`services/chart.py` を直す前に**今の `chart_text` を写した `legacy_chart_text` を置く（以後は変えない）
    - `test_R01_chart_unchanged_without_plan_ids`（性質6）：5場面の見本と、文なし・空白だけの文・句点なし・空白だけの文にだけ `plan_id`・`plan_id` の欄なし。患者は `care_plans` のある患者とない患者
    - `test_R01_chart_groups_by_care_plan`（性質7）：期待の `chart_text` を手で書いた (a)〜(g)（(d) 名簿にない `cp99` は計画外の欄、(f) 文の付かない計画は見出しも出ない、(g) requirements の 305号室の8行の例）。空でない文がちょうど1回、正しい行にあることも見る
    - `test_R01_chart_round_trip`（性質8）：(a)〜(e) と `plan_id` のない下書き。`record_document` → `Draft.model_validate` で `plan_id` と `chart_text` が同じ
    - _Requirements: 6.6, 8.1, 8.2, 8.3, 8.4, 8.5, 8.6, 8.7, 8.9, 8.10, 8.11, 8.12, 8.13, 8.14, 8.15_
  - [x] 2.4 カルテ用の文を看護計画ごとにまとめる（2.3 を通す）
    - `services/care_plan.py` に `plan_sections`（空の文を除く → `plan_id` がなければ `[]` → `care_plans` の並びで欄 → 計画外の欄を最後に1つ）
    - `services/chart.py` に `_soap_lines` を足し、`chart_text` で `plan_sections` を使う。関数の名前・引数・戻り値の型は変えない
    - 今の `test_S06_R01_chart_text_format`・`test_R01_sentence_without_period_gets_one`・`test_A06_kept_unsupported_sentence_is_marked_only_in_record` を変えずに通す
    - _Requirements: 8.1, 8.2, 8.3, 8.4, 8.5, 8.6, 8.7, 8.8, 8.9, 8.10, 8.11, 8.13, 8.14, 8.15_
  - [x] 2.5 起動時の確かめのテストを書く（落ちることを確かめる）
    - `tests/test_care_plan_models.py` に `test_SEC04_seed_care_plan_conditions`（性質1）：名簿seed の場所を差し替えて `load_patients()` を呼ぶ。正しい名簿と、0件・10件・11件、空・100字・101字・`\n`・`\r`・`\u2028`・全角の空白だけの `label`、`cp 01`・41字の `id`、患者の中の同じ `id`・同じ `label`、ほかの患者と同じ `id` の表。受け付けないときは `SeedInvalidError`、`seed_invalid` のログに `id`・`label` の文字列がない
    - `test_SEC04_bad_seed_stops_startup`：わざと壊した名簿seed（101字の `label`、ほかの患者と同じ `id`）× mock と、live の1例（101字）で `build_services` が `SeedInvalidError`。live は `FirestoreStore.connect` に届かない
    - _Requirements: 1.4, 1.5, 1.7, 1.9, 9.4_
  - [x] 2.6 起動時の確かめを作る（2.5 を通す）
    - `services/mock_data.py`：`SeedInvalidError`。`load_patients` で患者ごとに `Patient.model_validate`、名簿全体の `id` の重なり（`duplicate_care_plan_id`）を確かめ、`seed_invalid` のログ（`index`・`loc`・`type` だけ、先頭の5件まで）を出して `raise ... from None`
    - _Requirements: 1.4, 1.5, 1.7, 1.9, 9.4_
  - [x] 2.7 名簿API・受け持ちAPI・下書きAPI のテストを書く（落ちることを確かめる）
    - `tests/test_rules_care_plan_api.py`（新規）に次を書く
    - `test_S08_patients_return_care_plans`：mock の名簿API の `care_plans` が `load_patients()` と同じ。欄なし・`null`・`[]` の患者で `[]`
    - `test_S08_assignee_change_keeps_care_plans`：変えた出力とその後の名簿API が変える前と同じ。わざと壊した例：入力に別の `care_plans` を入れても変わらない
    - `test_A14_draft_plan_ids_null_and_patient_care_plans`：mock（p302）と live（`FakeGemini`、p305）で、`patient.care_plans` が選んだ患者の値、S・O の `plan_id` がすべて `null`
    - `test_A14_mock_file_plan_ids_are_reset`：わざと壊した例：`plan_id` を書き込んだ見本に差し替えても、下書きはすべて `null`
    - _Requirements: 2.1, 2.2, 2.3, 2.5, 2.6, 2.7, 4.1, 4.3_
  - [x] 2.8 ルートを直す（2.7 を通す）
    - `routes/deps.py`：`with_roster_care_plans`
    - `routes/patients.py`：名簿API・受け持ちAPI の `patient` に `with_roster_care_plans` をかける
    - `routes/drafts.py`：`clear_plan_ids` をかけてから `draft_token` を出す
    - _Requirements: 2.1, 2.2, 2.3, 2.5, 2.6, 2.7, 4.1, 4.3_

- [x] 3. Bさんと同じファイルの変更を先に push する（確定と保存先。11/19 20:00 より前）
  - 機能2の作業を渡すのではない。Bさんが機能2で触る `services/confirm.py`・`store/firestore_store.py` の機能1の変更を、Bさんが始める前に push してぶつからないようにする
  - [x] 3.1 確定のときの確かめのテストを書く（落ちることを確かめる）
    - `tests/test_rules_care_plan_api.py` に次を書く（live は `FakeGemini`・`FakeSpeech`・`FakeFirestore`）
    - `test_R03_other_patients_plan_is_422`：わざと壊した例：mock × p305 に `cp01`・`cp99`・`CP04`・消すと決めた文にだけ・看護師が足した文にだけ、と live の1例で 422 `unknown_care_plan`。`message` に「S 1文目」などがあり、`label` と送った値がない
    - `test_R03_confirm_uses_roster_care_plans`：`care_plans` が空の p305 を `confirm_record` に渡しても `cp04` の確定が通り、`chart_text` に `#急性疼痛` の行
    - `test_R03_unknown_plan_is_not_saved`：同じ `confirm_id` で確定の後に知らない `plan_id` で送り直すと 422、前の記録とタスクがそのまま
    - `test_R03_checked_before_patient_confirm_and_entail`：わざと壊した例：患者の照合が赤（p303）・文を直した・「止める」を決めていない下書きに知らない `plan_id` で 422（409 ではない）。`FakeGemini.calls` に `judge` がなく、上限の回数が増えない
    - `test_R03_missing_or_null_plan_id_confirms`：欄なし・すべて `null`・`care_plans` が空の名簿で 200、記録に `plan_id: null`
    - `test_R03_invalid_plan_id_form_is_invalid_request`：照合API・確定API × 空・41字・`cp 01`・`5`・`[]` で 422 `invalid_request`、`message` に `soap.S.0.plan_id`、送った値がない、`mode` がある。live の確定の1例で `FakeGemini.calls`・上限の回数・記録が増えない
    - `test_R03_plan_id_on_other_elements_is_dropped`：バイタル・依頼・手で入力・医師への確認の `plan_id` は捨て、記録とタスクにキーがない
    - _Requirements: 3.2, 3.3, 3.6, 3.8, 6.1, 6.2, 6.3, 6.5, 6.8, 6.9, 7.7, 10.3_
  - [x] 3.2 確定のログと記録のテストを書く（落ちることを確かめる）
    - `test_P04_confirm_log_has_plan_counts`：`record_confirmed` に `plan_sentences`・`unplanned_sentences`・`plans_used`・`plans_available`、0 でも省かない
    - `test_P04_unknown_care_plan_log_line`：`record_rejected` のキーが `{severity, event, code, unknown_plan_sentences}` だけ、`record_confirmed` が出ない
    - `test_P04_no_care_plan_strings_in_logs`：確定・`unknown_care_plan`・`seed_invalid` の流れの `app` のログのどの行にも、名簿のすべての `id`・`label`・`#` を除いた `label`・送った `plan_id` がない
    - `test_P03_record_has_no_care_plan_copy`：記録とタスクにその患者の `label` も `care_plans` のキーもない
    - _Requirements: 9.1, 9.2, 9.4, 9.5, 9.6, 9.7_
  - [x] 3.3 確定で看護計画を確かめる（3.1・3.2 を通す）
    - `services/confirm.py` の `confirm_record` の先頭で、`roster` から患者の `care_plans` を引き直し（`patient.model_copy`）、`ensure_known_care_plans(req.draft, patient.care_plans)` を `match_patient` より前に呼ぶ
    - `_log_confirmed` に `care_plan_counts` を足し、`plan_log_fields(final, patient.care_plans)` を渡す。docstring の Raises に `422`（`unknown_care_plan`）
    - `routes/records.py`・`services/record_documents.py` は変えない
    - _Requirements: 6.1, 6.2, 6.3, 6.4, 6.8, 6.9, 7.7, 9.1, 9.2, 9.3, 9.5, 9.6, 9.7, 10.1, 10.3_
  - [x] 3.4 `plan_id` だけの変更で照合・二段目が変わらないテストを書く
    - 変えないファイル（`checks/`・`services/entail_seal.py`・`services/draft_token.py` など）の事実を確かめるテストなので、コードは足さずに通る見込み。落ちたら design の事実が違うので、直す前に Cさんに相談する
    - `test_A04_A12_plan_only_change_keeps_checks_and_record`（性質4）：live の p302 で、(1) `plan_id` だけ（`soap.S[0]` に `cp01`、`soap.O[0]` に `cp02`）、(2) `text` を直して `plan_id` も付ける、を付けない下書きと比べる
    - `test_A04_edited_sentence_with_plan_is_judged_again`：`judge` が1回、`entail_rejudged` が1
    - `test_A12_split_ai_sentence_is_checked`：AI の文を分けた下書き（後半は同じ欄の最後に `added_by: "ai"`・同じ `evidence`・`plan_id: null`）で、2文が照合と二段目にかかり `judge` は1回。わざと壊した例：後半に根拠の発言にない数を入れると `number_not_in_evidence` で止まる
    - `test_A14_A09_care_plans_not_sent_to_gemini`：引数を覚える `FakeGemini` の差し替えで、下書き・照合（`entail: true`）・確定（文を直して呼び直し）の引数の `repr` に名簿のどの `id`・`label` もない
    - _Requirements: 3.4, 3.7, 4.2, 4.4, 6.4, 6.10, 7.1, 7.2, 7.3, 7.4, 7.6, 7.8_
  - [x] 3.5 記録閲覧と見本の場面のテストを書いて通す
    - `test_R01_record_view_rebuilds_same_chart`：mock で確定 → 記録閲覧の `chart_text` が1字も違わない
    - `test_R01_R03_record_view_after_roster_change`：確定の後に名簿の `care_plans` を差し替える／患者を外すと、記録閲覧が 200、`plan_id` は確定のときのまま、その文が「計画外」の欄にちょうど1回
    - `test_R03_old_record_without_plan_id_reads_null`：`plan_id` のない記録で `null` が返り、保存先は変わらない
    - `test_P07_mock_scenarios_have_attachable_sentences`：design「場面ごとの期待」の表の各行で、`plan_id` を入れた確定が 200、`chart_text` にその `label` の行
    - _Requirements: 6.6, 6.7, 8.12, 8.14, 10.2_
  - [x] 3.6 保存先が看護計画を持たないテストを書く（落ちることを確かめる）
    - `test_C07_S08_live_patients_use_roster_care_plans`：live（`FakeFirestore` に `seed_patients`）で、Firestore の文書に `care_plans` のキーがなく、`assigned_to` が残る。名簿API・受け持ちAPI の `care_plans` が mock と同じ
    - わざと壊した例：Firestore の文書に条件に合わない `care_plans`（101字の `label`）を手で入れても、同じ値を返し 500 にならない
    - _Requirements: 2.4, 2.9_
  - [x] 3.7 Firestore に看護計画を書かない・読まない（3.6 を通す）
    - `store/firestore_store.py`：`_ROSTER_ONLY_FIELDS`・`_stored_patient`。`seed_patients` は `exclude={"id", *_ROSTER_ONLY_FIELDS}`、`list_patients`・`get_patient`・`set_patient_assignee` は `_stored_patient` で作る
    - `store/memory.py`・`store/base.py` は変えない
    - _Requirements: 2.4, 2.9_
  - [x] 3.8 全テストを回して commit・push し、2つのファイルを触ってよくなったことを Bさんに知らせる
    - `cd backend && .venv/Scripts/python -m pytest -q && .venv/Scripts/ruff check . && .venv/Scripts/ruff format --check .` と `node --test frontend/tests/*.test.mjs`
    - 見本に関わる形を変えていれば `backend` で `python -m scripts.build_mocks` を回して一緒に commit する（`test_mock_file_is_up_to_date` で分かる）
    - push の後、Bさんに `services/confirm.py`・`store/firestore_store.py` を触ってよいことを知らせる
    - _Requirements: 2.9, 6.1, 10.5_

- [x] 4. 文書（11/19 中に push）
  - [x] 4.1 `docs/design/rules.md` を直す
    - design の「決まりの変更（rules.md に写す案）」の表を写す：R-01 の書き換え、A-14・R-03 の追加
    - A-09 の確かめ方に `test_A14_A09_care_plans_not_sent_to_gemini`、P-04 の確かめ方に `test_P04_no_care_plan_strings_in_logs`・`test_P04_confirm_log_plan_counts` を足す
    - 変更履歴に1行ずつ足す
    - _Requirements: 4.1, 4.2, 6.1, 6.2, 8.1, 8.7, 9.4_
  - [x] 4.2 `docs/design/data-model.md` を直す
    - design の「画面（Aさん）に渡すデータの形」を写す：3章（名簿API・受け持ちAPI・下書きAPI・照合API・確定API・記録閲覧API の欄と `unknown_care_plan`）、4章（`records` の `plan_id`。`patients` には `care_plans` を書かない）
    - 変更履歴に1行足す
    - _Requirements: 2.1, 2.3, 2.9, 3.1, 6.2, 6.4, 6.7_
  - [x] 4.3 `docs/submission/ai-usage-log.md` に1行足し、文書を commit・push する
    - pull してから足す（Aさん・Bさんも足すため）
    - _Requirements: なし（spec-guide.md の約束）_

- [x] 5. 最後の確かめ
  - [x] 5.1 テストを置かない受け入れ条件を確かめる（コードは AI が、名簿seed の label は 11/19 に Cさんが確かめた）
    - 人が名簿seed のすべての `label` を見て、架空であることを確かめる（提出前）
    - コードを読んで確かめる：確定の道（`confirm_record`・`chart_text`）に `mode` の分岐がない、`services/care_plan.py`・`services/chart.py` が外の部品を import しない、下書きと照合の上限の数え方を変えていない（今の `test_C04_*` のまま）
    - _Requirements: 1.6, 7.5, 10.1, 10.4_
  - [x] 5.2 バックエンドと画面の全テストを回す
    - 必ず次を回し、すべて通ることを確かめる
      ```bash
      cd backend && .venv/Scripts/python -m pytest -q && .venv/Scripts/ruff check . && .venv/Scripts/ruff format --check .
      node --test frontend/tests/*.test.mjs
      ```
    - _Requirements: 1.1〜10.5 のうち、テストのあるものすべて_

- [ ] 6. デプロイ
  - [ ] 6.1 **Cさんの承認が要る**（cost.md。費用の表を出して承認を取ってから行う。承認の前で止まる）
    - Firestore の `records` の書き込みの形が変わる（S・O の文に `plan_id`）。この機能で Gemini・Speech-to-Text の呼び出しは増えないが、そのときの単価で費用の表を作って Cさんに出す
    - 前の版に戻すと、Firestore の `patients` には何も起きないが、看護計画を付けて確定した記録は記録閲覧で `chart_text` が見出しのない形になり、出力画面が「保存した記録と表示内容が一致しません。」を出すことがある（記録は翌日0時以降に消える、P-03）
    - _Requirements: 2.9, 6.4, 6.7_
