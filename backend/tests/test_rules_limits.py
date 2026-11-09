"""SEC-04（入力の大きさ）と C-04（1日の上限）の、11/8 の批判で足した分。"""

from typing import Any

import pytest
from fastapi.testclient import TestClient

from app.main import create_app
from app.models.draft import Utterance
from app.models.gemini import GeminiDraft
from app.models.limits import MAX_UTTERANCES
from app.services.record_documents import MAX_SAVED_CHARS, evidence_utterances
from tests.fakes import S1_TRANSCRIPT, FakeGemini, FakeSpeech
from tests.helpers import HEADERS, draft_of, make_services, make_settings, post_text_draft


def _verify_body(client: TestClient) -> dict[str, Any]:
    draft = post_text_draft(client, "p302")
    return {"utterances": draft["utterances"], "draft": draft["draft"]}


def _live(per_client: int = 100, gemini: Any = None, **settings: Any) -> TestClient:
    services = make_services(gemini or FakeGemini(), FakeSpeech(), per_client=per_client)
    return TestClient(create_app(make_settings("live", **settings), services))


def _text_draft(client: TestClient, ip: str = "203.0.113.1") -> Any:
    headers = {**HEADERS, "X-Forwarded-For": f"{ip}, 10.0.0.1"}
    body = {"patient_id": "p302", "transcript": S1_TRANSCRIPT}
    return client.post("/api/drafts", json=body, headers=headers)


def test_SEC04_evidence_flood_is_rejected(mock_client: TestClient) -> None:
    """SEC-04：根拠を数万件並べた下書きは、二段目の入力を作る前に 422 で断る。"""
    body = _verify_body(mock_client)
    body["draft"]["soap"]["S"][0]["evidence"] = ["u1"] * 20000
    res = mock_client.post("/api/verify", json={**body, "entail": True}, headers=HEADERS)
    assert res.status_code == 422 and res.json()["error"]["code"] == "invalid_request"


def test_SEC04_evidence_duplicates_are_removed_but_four_ids_are_too_many(
    mock_client: TestClient,
) -> None:
    """SEC-04：根拠は重複を除いて3件まで。"""
    body = _verify_body(mock_client)
    body["draft"]["soap"]["S"][0]["evidence"] = ["u1", "u1", "u2"]
    assert mock_client.post("/api/verify", json=body, headers=HEADERS).status_code == 200
    body["draft"]["soap"]["S"][0]["evidence"] = ["u1", "u2", "u3", "u4"]
    assert mock_client.post("/api/verify", json=body, headers=HEADERS).status_code == 422


@pytest.mark.parametrize("where", ["utterances", "text"])
def test_SEC04_too_many_utterances_or_long_text_is_rejected(
    mock_client: TestClient, where: str
) -> None:
    """SEC-04：発言は200個まで、1つの文は5,000文字まで。"""
    body = _verify_body(mock_client)
    if where == "utterances":
        body["utterances"] = body["utterances"] * (MAX_UTTERANCES // len(body["utterances"]) + 1)
    else:
        body["draft"]["soap"]["S"][0]["text"] = "あ" * 5001
    assert mock_client.post("/api/verify", json=body, headers=HEADERS).status_code == 422


def test_SEC04_json_body_over_limit_is_413() -> None:
    """SEC-04：JSON の本文は上限（本番は 1MB）まで。Content-Length でも、chunked でも。"""
    services = make_services()
    client = TestClient(create_app(make_settings("mock", max_json_bytes=1000), services))
    headers = {**HEADERS, "Content-Type": "application/json"}
    res = client.post("/api/verify", content=b" " * 2000, headers=headers)
    assert res.status_code == 413 and res.json()["error"]["code"] == "body_too_large"
    res = client.post("/api/verify", content=iter([b" " * 600, b" " * 600]), headers=headers)
    assert res.status_code == 413 and res.json()["error"]["code"] == "body_too_large"


def test_SEC04_audio_is_refused_by_content_length_before_reading() -> None:
    """SEC-04：音声は Content-Length を先に見て、上限を大きく超えたら読まずに断る。"""
    speech = FakeSpeech()
    services = make_services(FakeGemini(), speech)
    client = TestClient(create_app(make_settings("live"), services))
    files = {"audio": ("a.webm", b"x" * 200_000, "audio/webm")}
    data = {"patient_id": "p302", "consent_confirmed": "true"}
    res = client.post("/api/drafts", data=data, files=files, headers=HEADERS)
    assert res.status_code == 413 and res.json()["error"]["code"] == "audio_too_large"
    assert speech.audio is None


def test_SEC04_saved_evidence_utterances_are_capped() -> None:
    """SEC-04：記録に残す根拠の発言は、文の長さに上限がある。"""
    draft = draft_of("s1")
    used = draft.soap.S[0].evidence[0]
    utterances = [Utterance(id=used, speaker="patient", text="あ" * 5000)]
    saved = evidence_utterances(draft, utterances)
    assert len(saved[0]["text"]) == MAX_SAVED_CHARS


@pytest.mark.parametrize(
    ("method", "url", "body"),
    [
        ("post", "/api/drafts", {"patient_id": "../p302", "transcript": "x"}),
        ("patch", "/api/tasks/bad!id", {"status": "done"}),
    ],
)
def test_SEC04_ids_must_be_simple(
    mock_client: TestClient, method: str, url: str, body: dict[str, Any]
) -> None:
    """SEC-04：patient_id・task_id は英数字・_・- の40文字まで。"""
    res = getattr(mock_client, method)(url, json=body, headers=HEADERS)
    assert res.status_code == 422


def test_C04_per_client_limit_counts_by_forwarded_ip() -> None:
    """C-04：全体の上限に加え、接続元（X-Forwarded-For の先頭）ごとの上限がある。"""
    client = _live(per_client=2)  # テキストの下書きは1回で2回分
    assert _text_draft(client).status_code == 200
    res = _text_draft(client)
    assert res.status_code == 429 and res.json()["error"]["code"] == "client_daily_limit"
    assert _text_draft(client, ip="198.51.100.7").status_code == 200


def test_C04_failed_draft_gives_calls_back() -> None:
    """C-04：失敗した下書きの分は回数を戻す（失敗が続いても上限で締め出さない）。"""

    class Broken(FakeGemini):
        def generate_draft(self, utterances: list) -> GeminiDraft:
            raise RuntimeError("down")

    client = _live(per_client=2, gemini=Broken())
    for _ in range(3):
        assert _text_draft(client).status_code == 502
