"""MODE=live の流れを、Gemini・Speech-to-Text を差し替えて確かめる（実際には呼ばない）。"""

from typing import Any

from fastapi.testclient import TestClient

from app.main import create_app
from app.models.draft import Utterance
from app.models.gemini import GeminiDraft
from tests.fakes import S1_TRANSCRIPT, FakeGemini, FakeSpeech
from tests.helpers import HEADERS, make_services, make_settings, utterances_of


def _client(gemini: Any, speech: Any = None, limit: int = 100) -> TestClient:
    return TestClient(create_app(make_settings("live"), make_services(gemini, speech, limit)))


def _text_draft(client: TestClient) -> Any:
    return client.post(
        "/api/drafts", json={"patient_id": "p302", "transcript": S1_TRANSCRIPT}, headers=HEADERS
    )


def test_text_draft_runs_pipeline() -> None:
    gemini = FakeGemini()
    res = _text_draft(_client(gemini))
    body = res.json()
    assert res.status_code == 200 and body["mode"] == "live" and body["input"] == "text"
    assert gemini.calls == ["draft", "judge"]
    assert body["utterances"][0] == {
        "id": "u1", "speaker": "nurse", "start": None, "end": None, "text": utterances_of("s1")[0].text,
    }  # fmt: skip
    assert body["checks"] == [] and body["missing"] == ["呼吸数", "SpO2"]
    assert body["patient_match"]["level"] == "ok"


def test_A09_only_utterances_are_sent_to_gemini() -> None:
    gemini = FakeGemini()
    _text_draft(_client(gemini))
    assert all(isinstance(u, Utterance) for u in gemini.seen_utterances)  # 発言の列だけを渡す


def test_audio_draft_uses_speech() -> None:
    gemini, speech = FakeGemini(), FakeSpeech()
    res = _client(gemini, speech).post(
        "/api/drafts",
        data={"patient_id": "p302", "consent_confirmed": "true"},
        files={"audio": ("a.webm", b"abc", "audio/webm")},
        headers=HEADERS,
    )
    assert res.status_code == 200 and res.json()["input"] == "audio"
    assert speech.audio == b"abc"


def test_audio_too_large() -> None:
    res = _client(FakeGemini(), FakeSpeech()).post(
        "/api/drafts",
        data={"patient_id": "p302", "consent_confirmed": "true"},
        files={"audio": ("a.webm", b"x" * 2000, "audio/webm")},
        headers=HEADERS,
    )
    assert res.status_code == 413


def test_C06_entail_failure_flags_every_sentence() -> None:
    body = _text_draft(_client(FakeGemini(judge_error=RuntimeError("timeout")))).json()
    codes = {(c["path"], c["code"]) for c in body["checks"]}
    assert ("soap.S[0]", "entail_unclear") in codes
    assert ("doctor_questions[0]", "entail_unclear") in codes


def test_C05_draft_failure_is_502() -> None:
    class Broken(FakeGemini):
        def generate_draft(self, utterances: list[Utterance]) -> GeminiDraft:
            raise RuntimeError("quota")

    res = _text_draft(_client(Broken()))
    assert res.status_code == 502 and res.json()["error"]["code"] == "draft_failed"


def test_C04_daily_limit_stops_before_calling() -> None:
    gemini = FakeGemini()
    client = _client(gemini, limit=3)
    assert _text_draft(client).status_code == 200
    res = _text_draft(client)
    assert res.status_code == 429 and gemini.calls == ["draft", "judge"]


def test_verify_entail_calls_gemini_once() -> None:
    gemini = FakeGemini()
    client = _client(gemini)
    draft = _text_draft(client).json()
    gemini.calls.clear()
    body = {"utterances": draft["utterances"], "draft": draft["draft"], "entail": True}
    assert client.post("/api/verify", json=body, headers=HEADERS).status_code == 200
    assert gemini.calls == ["judge"]
