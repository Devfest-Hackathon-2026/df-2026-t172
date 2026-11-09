"""A-12：看護師が足した要素（added_by=nurse）と、タスクを直接作る POST /api/tasks。"""

import json
import logging
from typing import Any

import pytest
from fastapi.testclient import TestClient

from app.main import create_app
from tests.fakes import S1_TRANSCRIPT, FakeGemini
from tests.helpers import HEADERS, make_services, make_settings, post_text_draft, record_body

NURSE_REQUEST = {
    "text": "お茶を持ってきてほしい",
    "urgency": "timed",
    "cue": {"kind": "時間指定", "text": "15時", "evidence": []},
    "evidence": [],
    "added_by": "nurse",
}


@pytest.fixture
def app_and_store() -> tuple[TestClient, Any]:
    """保存先（メモリ）をのぞけるようにする。"""
    services = make_services()
    return TestClient(create_app(make_settings("mock"), services)), services.store


def _confirm(client: TestClient, draft: dict[str, Any], **overrides: Any) -> Any:
    return client.post("/api/records", json=record_body(draft, **overrides), headers=HEADERS)


def _unused_patient_utterance(draft: dict[str, Any]) -> dict[str, Any]:
    """どの要素の根拠にもなっていない、患者の発言。"""
    used = json.dumps(draft["draft"])
    return next(
        u for u in draft["utterances"] if u["speaker"] == "patient" and f'"{u["id"]}"' not in used
    )


def test_A12_nurse_request_is_confirmed_without_ai_checks(
    app_and_store: tuple, caplog: pytest.LogCaptureFixture
) -> None:
    """A-12：看護師が足した依頼は根拠なしでも止まらず、看護師が決めた緊急度でタスクになる。"""
    client, store = app_and_store
    draft = post_text_draft(client, "p302")
    draft["draft"]["requests"].append(NURSE_REQUEST)
    with caplog.at_level(logging.INFO):
        res = _confirm(client, draft)
    assert res.status_code == 200, res.text
    record = store._records[res.json()["record_id"]]  # テストでだけ中をのぞく
    assert record["requests"][-1]["added_by"] == "nurse"
    assert record["kept_after_check"] == []  # 「AI の文を看護師が認めた」とは別
    task = store._tasks[res.json()["tasks_created"][-1]]
    assert (task["urgency"], task["urgency_set_by"]) == ("timed", "nurse")
    logs = [json.loads(r.getMessage()) for r in caplog.records if r.name == "app"]
    confirmed = next(e for e in logs if e["event"] == "record_confirmed")
    assert confirmed["nurse_added"] == 1 and confirmed["relabelled_as_ai"] == 0


def test_A12_P02_nurse_evidence_is_kept_as_patient_words(app_and_store: tuple) -> None:
    """A-12・P-02：看護師が選んだ根拠の発言は、タスクの patient_words と記録に残る。"""
    client, store = app_and_store
    draft = post_text_draft(client, "p302")
    chosen = _unused_patient_utterance(draft)
    draft["draft"]["requests"].append({**NURSE_REQUEST, "evidence": [chosen["id"]]})
    res = _confirm(client, draft)
    assert res.status_code == 200, res.text
    record = store._records[res.json()["record_id"]]
    assert chosen["id"] in {u["id"] for u in record["evidence_utterances"]}
    assert store._tasks[res.json()["tasks_created"][-1]]["patient_words"] == [chosen["text"]]


@pytest.mark.parametrize("url", ["/api/verify", "/api/records"])
def test_A12_nurse_evidence_must_exist(mock_client: TestClient, url: str) -> None:
    """A-12：看護師が足した要素の根拠は任意だが、付けるなら会話にある番号だけ（ない番号は 422）。"""
    draft = post_text_draft(mock_client, "p302")
    draft["draft"]["soap"]["O"].append(
        {"text": "創部確認", "evidence": ["u999"], "added_by": "nurse"}
    )
    body = record_body(draft) if url == "/api/records" else {
        "utterances": draft["utterances"], "draft": draft["draft"]
    }  # fmt: skip
    res = mock_client.post(url, json=body, headers=HEADERS)
    assert res.status_code == 422 and res.json()["error"]["code"] == "unknown_evidence"


def test_A12_nurse_sentence_skips_code_checks_and_gemini() -> None:
    """A-12：看護師が足した文には照合（薬の語・根拠なし）も二段目もかけず、Gemini も呼ばない。"""
    gemini = FakeGemini()
    client = TestClient(create_app(make_settings("live"), make_services(gemini)))
    draft = post_text_draft(client, "p302", S1_TRANSCRIPT)
    draft["draft"]["soap"]["O"].append({"text": "ロキソニン2錠内服済み", "added_by": "nurse"})
    path = f"soap.O[{len(draft['draft']['soap']['O']) - 1}]"
    verified = client.post(
        "/api/verify",
        json={"utterances": draft["utterances"], "draft": draft["draft"]},
        headers=HEADERS,
    ).json()
    assert [c for c in verified["checks"] if c["path"] == path] == []
    assert _confirm(client, draft).status_code == 200
    assert gemini.calls == ["draft", "judge"]  # 確定のときに呼び直していない


@pytest.mark.parametrize("with_token", [True, False])
def test_A12_ai_sentence_cannot_pose_as_nurse(mock_client: TestClient, with_token: bool) -> None:
    """A-12：下書きにあった文を「看護師が足した」にしても AI の文として照合する。

    draft_token がない・合わないときは、看護師が足した要素をすべて AI の要素として扱う。
    """
    draft = post_text_draft(mock_client, "p308")  # soap.S[2] が二段目で止まる
    draft["draft"]["soap"]["S"][2]["added_by"] = "nurse"
    token = draft["draft_token"] if with_token else "forged.token"
    res = _confirm(mock_client, draft, draft_token=token)
    assert res.status_code == 409 and res.json()["error"]["code"] == "undecided_checks"


def test_A12_create_task_directly(mock_client: TestClient) -> None:
    """A-12：POST /api/tasks は記録なしでタスクを作る（record_id は null、urgency_set_by は nurse）。"""
    body = {
        "patient_id": "p305",
        "text": "  家族に電話してほしい  ",
        "urgency": "said_urgent",
        "cue": {"kind": "患者が急ぎと言った", "text": "今日中に"},
        "patient_words": ["娘に今日中に電話したいの"],
    }
    res = mock_client.post("/api/tasks", json=body, headers=HEADERS)
    assert res.status_code == 200, res.text
    task = res.json()["task"]
    assert task["text"] == "家族に電話してほしい" and task["record_id"] is None
    assert (task["urgency"], task["urgency_set_by"]) == ("said_urgent", "nurse")
    assert task["patient_words"] == body["patient_words"] and task["room"] == "305"
    listed = mock_client.get("/api/tasks", headers=HEADERS).json()["tasks"]
    assert task["id"] in {t["id"] for t in listed}


@pytest.mark.parametrize(
    ("body", "status"),
    [
        ({"patient_id": "p305", "text": "   "}, 422),  # 空の文
        ({"patient_id": "../p305", "text": "x"}, 422),  # id の形でない
        ({"patient_id": "p999", "text": "x"}, 404),  # 名簿にいない
        ({"patient_id": "p305", "text": "x", "patient_words": ["a"] * 4}, 422),  # 4件以上
        ({"patient_id": "p305", "text": "x", "urgency": "最優先"}, 422),
    ],
)
def test_SEC04_create_task_input_is_checked(
    mock_client: TestClient, body: dict[str, Any], status: int
) -> None:
    """SEC-04：直接作るタスクも、id の形・名簿・上限を確かめる。"""
    assert mock_client.post("/api/tasks", json=body, headers=HEADERS).status_code == status


def test_SEC01_create_task_needs_passcode(mock_client: TestClient) -> None:
    """SEC-01：タスクを作るにも合言葉が要る。"""
    res = mock_client.post("/api/tasks", json={"patient_id": "p305", "text": "x"})
    assert res.status_code == 401
