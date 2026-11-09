"""docs/design/rules.md の決まりのうち、入力・AI の扱い・ログ・失敗時にかかわるもの。"""

import logging
from typing import Any

import pytest
from fastapi.testclient import TestClient

from app.config import load_settings
from app.live.interfaces import PreparedAudio
from app.main import create_app
from app.models.draft import Utterance
from app.models.gemini import GeminiDraft
from tests.fakes import S1_TRANSCRIPT, FakeGemini, FakeSpeech
from tests.helpers import HEADERS, SCENARIOS, make_services, make_settings, utterances_of


def _live(gemini: Any = None, speech: Any = None, **settings: Any) -> TestClient:
    services = make_services(gemini or FakeGemini(), speech)
    return TestClient(create_app(make_settings("live", **settings), services))


def _post_audio(client: TestClient, **form: str) -> Any:
    data = {"patient_id": "p302", "consent_confirmed": "true", **form}
    files = {"audio": ("a.webm", b"abc", "audio/webm")}
    return client.post("/api/drafts", data=data, files=files, headers=HEADERS)


def test_A02_a_and_p_from_ai_are_discarded() -> None:
    """A-02：AI の出力に A・P が入っていても捨て、常に空で返す。"""

    class GeminiWritingAP(FakeGemini):
        def generate_draft(self, utterances: list[Utterance]) -> GeminiDraft:
            data = {**SCENARIOS["s1"]["gemini_draft"], "A": "感染の疑い", "P": "抗生剤を開始"}
            return GeminiDraft.model_validate(data)

    client = _live(GeminiWritingAP())
    body = client.post(
        "/api/drafts", json={"patient_id": "p302", "transcript": S1_TRANSCRIPT}, headers=HEADERS
    ).json()
    assert body["draft"]["soap"]["A"] == "" and body["draft"]["soap"]["P"] == ""


def test_A09_selected_patient_is_not_sent_to_gemini() -> None:
    """A-09：Gemini に渡すのは発言の列だけ（選んだ患者は渡さない）。"""
    gemini = FakeGemini()
    _live(gemini).post(
        "/api/drafts",
        json={"patient_id": "p305", "transcript": "看護師: 熱を測ります"},
        headers=HEADERS,
    )
    assert "佐藤" not in "".join(u.text for u in gemini.seen_utterances)


def test_P04_logs_have_no_conversation_or_patient_name(caplog: pytest.LogCaptureFixture) -> None:
    """P-04：失敗の例外に会話の文が入っていても、ログには種類だけを出す。"""
    secret = "傷がさ、夜中ちょっとズキズキして"

    class Leaky(FakeGemini):
        def generate_draft(self, utterances: list[Utterance]) -> GeminiDraft:
            raise ValueError(f"検証に失敗: {secret}")

    with caplog.at_level(logging.DEBUG):
        _live(Leaky()).post(
            "/api/drafts", json={"patient_id": "p302", "transcript": S1_TRANSCRIPT}, headers=HEADERS
        )
        client = TestClient(create_app(make_settings("mock"), make_services()))
        draft = client.post(
            "/api/drafts", json={"patient_id": "p302", "transcript": "x"}, headers=HEADERS
        ).json()
        body = {
            "confirm_id": "c1",
            "patient_id": "p302",
            "utterances": draft["utterances"],
            "draft": draft["draft"],
        }
        client.post("/api/records", json=body, headers=HEADERS)
    logs = "\n".join(r.getMessage() for r in caplog.records)
    assert '"error_type": "ValueError"' in logs and '"record_confirmed"' in logs
    assert secret not in logs and "田中" not in logs
    assert not any(r.exc_info for r in caplog.records)  # スタックトレースも出さない


def test_SEC04_audio_over_3_minutes_is_413() -> None:
    """SEC-04：音声は3分まで（画面が送る長さで、呼ぶ前に止める）。"""
    speech = FakeSpeech()
    assert _post_audio(_live(speech=speech), duration_seconds="181").status_code == 413
    assert speech.audio is None


def test_SEC04_audio_found_long_when_read_is_413() -> None:
    """SEC-04：長さが送られなくても、読んだ音声が3分を超えたら、認識も Gemini も呼ばずに止める。"""
    gemini, speech = FakeGemini(), FakeSpeech(seconds=200.0)
    assert _post_audio(_live(gemini, speech)).status_code == 413
    assert not speech.transcribed
    assert gemini.calls == []


def test_SEC04_audio_found_long_after_transcription_is_413() -> None:
    """SEC-04：文字起こしの時刻が3分を超えたときも止める（Gemini は呼ばない）。"""

    class LongSpeech(FakeSpeech):
        def transcribe(self, prepared: PreparedAudio) -> list[Utterance]:
            return [Utterance(id="u1", speaker="nurse", start=0.0, end=200.0, text="…")]

    gemini = FakeGemini()
    assert _post_audio(_live(gemini, LongSpeech())).status_code == 413
    assert gemini.calls == []


def test_SEC04_audio_over_size_is_413() -> None:
    """SEC-04：音声は 10MB まで（テストでは上限を 1KB にしている）。"""
    client = _live(speech=FakeSpeech())
    files = {"audio": ("a.webm", b"x" * 2000, "audio/webm")}
    data = {"patient_id": "p302", "consent_confirmed": "true"}
    assert client.post("/api/drafts", data=data, files=files, headers=HEADERS).status_code == 413


def test_SEC04_text_over_5000_chars_is_413(mock_client: TestClient) -> None:
    """SEC-04：テキストは5,000文字まで。"""
    body = {"patient_id": "p302", "transcript": "あ" * 5001}
    res = mock_client.post("/api/drafts", json=body, headers=HEADERS)
    assert res.status_code == 413 and res.json()["error"]["code"] == "transcript_too_long"


def test_SEC05_unexpected_error_hides_internals() -> None:
    """SEC-05：思わぬ例外でも、応答に内部の情報を出さない。"""
    services = make_services()
    services.store.list_tasks = lambda *_: 1 / 0  # type: ignore[method-assign]
    # ErrorGuard が投げ直しを受け止めるので、raise_server_exceptions を外さなくてよい
    client = TestClient(create_app(make_settings("mock"), services))
    res = client.get("/api/tasks", headers=HEADERS)
    assert res.status_code == 500
    assert res.json() == {
        "mode": "mock",
        "error": {
            "code": "internal_error",
            "message": "サーバーでエラーが起きました。もう一度お試しください",
        },
    }


def test_C04_daily_limit_default_is_300(monkeypatch: pytest.MonkeyPatch) -> None:
    """C-04：1日の回数上限は 300回/日。"""
    monkeypatch.setenv("PASSCODE", "x" * 12)
    monkeypatch.delenv("DAILY_CALL_LIMIT", raising=False)
    assert load_settings().daily_call_limit == 300


def test_C05_failure_is_reported_not_replaced_by_mock() -> None:
    """C-05：Gemini が失敗したら、モックに切り替えずに分かる言葉で返す。"""

    class Broken(FakeGemini):
        def generate_draft(self, utterances: list[Utterance]) -> GeminiDraft:
            raise RuntimeError("quota")

    res = _live(Broken()).post(
        "/api/drafts", json={"patient_id": "p302", "transcript": S1_TRANSCRIPT}, headers=HEADERS
    )
    assert res.status_code == 502
    assert res.json()["mode"] == "live" and "draft" not in res.json()


def test_C07_mode_in_every_response(mock_client: TestClient) -> None:
    """C-07：成功・エラーのどちらの応答にも mode が入る。"""
    for res in (
        mock_client.get("/api/patients", headers=HEADERS),
        mock_client.get("/api/tasks", headers=HEADERS),
        mock_client.get("/api/patients"),
        mock_client.get("/api/nothing", headers=HEADERS),
    ):
        assert res.json()["mode"] == "mock"


@pytest.mark.parametrize("consent", [None, "false"])
def test_O01_audio_without_consent_is_400(consent: str | None) -> None:
    """O-01：録音の API は、患者の同意を確かめた印（consent_confirmed=true）がなければ 400。"""
    speech = FakeSpeech()
    data = {"patient_id": "p302"} | ({"consent_confirmed": consent} if consent else {})
    files = {"audio": ("a.webm", b"abc", "audio/webm")}
    res = _live(speech=speech).post("/api/drafts", data=data, files=files, headers=HEADERS)
    assert res.status_code == 400 and res.json()["error"]["code"] == "consent_required"
    assert speech.audio is None


def test_S08_patients_are_ward_list_by_room(mock_client: TestClient) -> None:
    """S-08：名簿は病棟の患者一覧（部屋番号の順）。全員に、一覧にいる受け持ちの看護師がいる。"""
    patients = mock_client.get("/api/patients", headers=HEADERS).json()["patients"]
    nurses = mock_client.get("/api/nurses", headers=HEADERS).json()["nurses"]
    assert [p["room"] for p in patients] == sorted(p["room"] for p in patients)
    assert {p["assigned_to"] for p in patients} <= {n["id"] for n in nurses}


def test_S01_conversation_does_not_change_selected_patient() -> None:
    """S-01：会話で別の部屋を言っても、患者は選んだまま（照合で赤にするだけ）。"""
    client = _live()
    body = client.post(
        "/api/drafts",
        json={
            "patient_id": "p305",
            "transcript": "\n".join(f"看護師: {u.text}" for u in utterances_of("s1")),
        },
        headers=HEADERS,
    ).json()
    assert body["patient"]["id"] == "p305" and body["patient_match"]["level"] == "stop"
