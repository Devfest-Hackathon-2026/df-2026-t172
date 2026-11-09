"""最初に話す人の指定（first_speaker）。Gemini に下書きを作らせる前に話者を合わせる。"""

from typing import Any

import pytest
from fastapi.testclient import TestClient

from app.main import create_app
from app.models.draft import Utterance
from app.services.first_speaker import apply_to_audio, apply_to_text
from tests.fakes import FakeGemini, FakeSpeech
from tests.helpers import HEADERS, make_services, make_settings


def utt(*speakers: str) -> list[Utterance]:
    return [Utterance(id=f"u{i}", speaker=s, text="…") for i, s in enumerate(speakers, 1)]  # type: ignore[arg-type]


def speakers(utterances: list[Utterance]) -> list[str]:
    return [u.speaker for u in utterances]


@pytest.mark.parametrize(
    ("given", "first", "want"),
    [
        (("nurse", "patient", "nurse"), "patient", ["patient", "nurse", "patient"]),
        (("nurse", "patient", "nurse"), "nurse", ["nurse", "patient", "nurse"]),
        (("nurse", "patient", "nurse"), "auto", ["nurse", "patient", "nurse"]),
        (("unknown", "patient", "nurse"), "patient", ["unknown", "patient", "nurse"]),
        (("unknown", "patient", "unknown"), "nurse", ["unknown", "nurse", "unknown"]),
    ],
    ids=[
        "逆なら全部入れ替える",
        "合っていればそのまま",
        "auto は何もしない",
        "最初の決まった話者で見る",
        "不明はそのまま",
    ],
)
def test_audio_follows_first_speaker(given: tuple[str, ...], first: Any, want: list[str]) -> None:
    assert speakers(apply_to_audio(utt(*given), first)) == want


def test_text_without_prefixes_alternates_from_first_speaker() -> None:
    got = apply_to_text(utt("unknown", "unknown", "unknown"), "patient")
    assert speakers(got) == ["patient", "nurse", "patient"]


def test_text_prefixes_win_over_first_speaker() -> None:
    given = utt("nurse", "patient", "unknown")
    assert speakers(apply_to_text(given, "patient")) == ["nurse", "patient", "unknown"]


class RecordingGemini(FakeGemini):
    """Gemini に渡った発言の列の話者を覚える。"""

    def generate_draft(self, utterances: list[Utterance]) -> Any:
        self.speakers = speakers(utterances)
        return super().generate_draft(utterances)


def _client(gemini: Any) -> TestClient:
    services = make_services(gemini, FakeSpeech())
    return TestClient(create_app(make_settings("live"), services))


def test_first_speaker_is_applied_before_gemini() -> None:
    """音声の指定は、Gemini に下書きを作らせる前に効く（後から入れ替えても下書きは直らないため）。"""
    gemini = RecordingGemini()
    data = {"patient_id": "p302", "consent_confirmed": "true", "first_speaker": "patient"}
    files = {"audio": ("a.webm", b"abc", "audio/webm")}
    res = _client(gemini).post("/api/drafts", data=data, files=files, headers=HEADERS)
    assert res.status_code == 200, res.text
    assert gemini.speakers[0] == "patient"
    assert res.json()["utterances"][0]["speaker"] == "patient"


def test_text_first_speaker_is_used_when_lines_have_no_speaker() -> None:
    gemini = RecordingGemini()
    body = {
        "patient_id": "p302",
        "transcript": "こんにちは\n熱を測りますね",
        "first_speaker": "nurse",
    }
    res = _client(gemini).post("/api/drafts", json=body, headers=HEADERS)
    assert res.status_code == 200, res.text
    assert gemini.speakers == ["nurse", "patient"]


def test_invalid_first_speaker_is_422() -> None:
    data = {"patient_id": "p302", "consent_confirmed": "true", "first_speaker": "doctor"}
    files = {"audio": ("a.webm", b"abc", "audio/webm")}
    res = _client(FakeGemini()).post("/api/drafts", data=data, files=files, headers=HEADERS)
    assert res.status_code == 422 and res.json()["error"]["code"] == "invalid_request"
