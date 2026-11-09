"""タスクの「患者の発言そのまま」（patient_words）。保存は P-02 の範囲に収める。"""

from fastapi.testclient import TestClient

from app.models.draft import Cue, PatientRequest, Utterance
from app.services.record_documents import MAX_PATIENT_WORDS, MAX_SAVED_CHARS, patient_words
from tests.helpers import HEADERS, post_text_draft, record_body


def _utterance(uid: str, speaker: str, text: str) -> Utterance:
    return Utterance(id=uid, speaker=speaker, text=text)


def test_P02_task_shows_patient_words_of_its_evidence(mock_client: TestClient) -> None:
    """P-02：確定したタスクに、依頼の根拠になった患者の発言そのままが入る（一覧と更新の出力）。"""
    draft = post_text_draft(mock_client, "p302")
    request = draft["draft"]["requests"][0]
    texts = {u["id"]: u["text"] for u in draft["utterances"]}
    res = mock_client.post("/api/records", json=record_body(draft), headers=HEADERS)
    [task_id] = res.json()["tasks_created"]

    tasks = mock_client.get("/api/tasks", headers=HEADERS).json()["tasks"]
    task = next(t for t in tasks if t["id"] == task_id)
    assert task["patient_words"] == [texts[e] for e in request["evidence"]]
    assert task["patient_words"] != [task["text"]]  # AI がまとめた文とは別の欄

    patched = mock_client.patch(f"/api/tasks/{task_id}", json={"status": "done"}, headers=HEADERS)
    assert patched.json()["task"]["patient_words"] == task["patient_words"]


def test_P02_patient_words_exclude_nurse_and_unrelated_utterances() -> None:
    """P-02：看護師の発言と、根拠でない発言（雑談）は入れない。順は発言の順。"""
    utterances = [
        _utterance("u1", "patient", "孫が来てね"),  # 根拠でない雑談
        _utterance("u2", "nurse", "何かありますか"),
        _utterance("u3", "unknown", "お茶がほしい"),
        _utterance("u4", "patient", "早めにね"),
    ]
    request = PatientRequest(
        text="お茶を持ってきてほしい",
        evidence=["u3", "u2"],
        cue=Cue(kind="患者が急ぎと言った", text="早めに", evidence=["u4"]),
    )
    assert patient_words(request, utterances) == ["お茶がほしい", "早めにね"]


def test_P02_patient_words_are_capped() -> None:
    """P-02：件数（3件）と字数（各1,000字）に上限がある。"""
    utterances = [_utterance(f"u{i}", "patient", "あ" * 3000) for i in range(1, 6)]
    request = PatientRequest(
        text="依頼",
        evidence=["u1", "u2", "u3"],
        cue=Cue(kind="時間指定", text="昼", evidence=["u4", "u5"]),
    )
    words = patient_words(request, utterances)
    assert len(words) == MAX_PATIENT_WORDS
    assert all(len(w) == MAX_SAVED_CHARS for w in words)


def test_P02_demo_tasks_have_patient_words(mock_client: TestClient) -> None:
    """モックの見本タスクにも、患者の発言そのままが入っている。"""
    tasks = mock_client.get("/api/tasks", headers=HEADERS).json()["tasks"]
    demo = [t for t in tasks if t["id"].startswith("t_demo")]
    assert demo and all(t["patient_words"] for t in demo)
