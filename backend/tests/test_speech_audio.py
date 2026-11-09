"""音声の経路：FLAC への変換・区切って続ける認識・呼び出しの数え方・話者の入れ替え。

本物の Speech-to-Text は呼ばない（client を差し替える）。ffmpeg は、入っていなければ飛ばす。
"""

import json
import logging
import shutil
import subprocess
from datetime import timedelta
from pathlib import Path
from types import SimpleNamespace as NS
from typing import Any

import pytest
from fastapi.testclient import TestClient

from app.live.audio_flac import AudioUnreadable, decode_pcm, pcm_seconds
from app.live.interfaces import PreparedAudio
from app.live.speech_v2 import GoogleSpeech, billed_seconds
from app.main import create_app
from app.services.audio_chunks import chunk_spans
from app.services.utterances import Word, utterances_from_words
from tests.fakes import FakeGemini, FakeSpeech
from tests.helpers import HEADERS, make_services, make_settings, post_text_draft

needs_ffmpeg = pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="ffmpeg がない")


def _post_audio(client: TestClient) -> Any:
    data = {"patient_id": "p302", "consent_confirmed": "true"}
    files = {"audio": ("a.m4a", b"abc", "audio/mp4")}
    return client.post("/api/drafts", data=data, files=files, headers=HEADERS)


def _sine_m4a(seconds: float, folder: Path) -> bytes:
    """テスト用の音（声ではない）を m4a で作る（m4a は標準出力に書けないので一時フォルダに）。"""
    path = folder / "sine.m4a"
    subprocess.run(
        ["ffmpeg", "-nostdin", "-loglevel", "error", "-f", "lavfi",
         "-i", f"sine=frequency=440:duration={seconds}", "-c:a", "aac", str(path)],
        check=True,
    )  # fmt: skip
    return path.read_bytes()


@needs_ffmpeg
def test_m4a_is_decoded_and_sent_as_flac_in_overlapping_pieces(tmp_path: Path) -> None:
    """m4a を読み、55秒ずつ5秒重ねた FLAC にして送り、時刻を通しの秒でつなぐ。"""
    sent: list[bytes] = []

    class Client:
        def recognize(self, request: Any, timeout: float) -> Any:
            sent.append(request.content)
            word = NS(word="はい", start_offset=timedelta(seconds=10), end_offset=timedelta(seconds=10.5), speaker_label="1")  # fmt: skip
            alt = NS(words=[word], transcript="はい")
            return NS(results=[NS(alternatives=[alt], result_end_offset=timedelta(seconds=11))])

    speech = GoogleSpeech("p", "us", "chirp_3", client=Client())
    prepared = speech.prepare(_sine_m4a(62.5, tmp_path))
    assert 62 <= prepared.seconds <= 63
    assert prepared.calls == 2
    utterances = speech.transcribe(prepared)
    assert len(sent) == 2 and all(data.startswith(b"fLaC") for data in sent)
    assert [u.start for u in utterances] == [10.0, 60.0]  # 2つ目は 50秒から始まる区切り


@needs_ffmpeg
def test_words_after_the_end_of_audio_are_dropped(tmp_path: Path) -> None:
    """録音の終わりより後の時刻の語（11/8 の検証で出た「あ」）は発言にしない。"""

    class Client:
        def recognize(self, request: Any, timeout: float) -> Any:
            words = [
                NS(word="はい", start_offset=timedelta(seconds=1), end_offset=timedelta(seconds=1.5), speaker_label="1"),
                NS(word="あ", start_offset=timedelta(seconds=5), end_offset=timedelta(seconds=5.1), speaker_label="2"),
            ]  # fmt: skip
            alt = NS(words=words, transcript="はいあ")
            return NS(results=[NS(alternatives=[alt], result_end_offset=timedelta(seconds=5))])

    speech = GoogleSpeech("p", "us", "chirp_3", client=Client())
    utterances = speech.transcribe(speech.prepare(_sine_m4a(3.0, tmp_path)))
    assert [u.text for u in utterances] == ["はい"]


@needs_ffmpeg
def test_unreadable_audio_raises() -> None:
    with pytest.raises(AudioUnreadable):
        decode_pcm(b"not audio")


@needs_ffmpeg
def test_decoded_pcm_is_16khz_mono(tmp_path: Path) -> None:
    assert round(pcm_seconds(decode_pcm(_sine_m4a(3.0, tmp_path)))) == 3


def test_audio_calls_are_counted_per_piece() -> None:
    """C-04：音声の下書きは、① 下書き ② 二段目 に、文字起こしの区切りの数を足して数える。"""
    long_audio = FakeSpeech(seconds=130.0)  # 区切りは3つ → 2 + 3 = 5回
    client = TestClient(
        create_app(make_settings("live"), make_services(FakeGemini(), long_audio, limit=4))
    )
    res = _post_audio(client)
    assert res.status_code == 429 and not long_audio.transcribed
    client = TestClient(
        create_app(make_settings("live"), make_services(FakeGemini(), FakeSpeech(130.0), limit=5))
    )
    assert _post_audio(client).status_code == 200


def test_unreadable_audio_is_422() -> None:
    class Unreadable(FakeSpeech):
        def prepare(self, audio: bytes) -> PreparedAudio:
            raise AudioUnreadable("読めない")

    client = TestClient(
        create_app(make_settings("live"), make_services(FakeGemini(), Unreadable()))
    )
    res = _post_audio(client)
    assert res.status_code == 422 and res.json()["error"]["code"] == "audio_unreadable"


def test_patient_speaking_first_is_swapped_by_nurse_likeness() -> None:
    """患者が先に話しても、部屋番号・バイタルを言った側を看護師にする（11/8 の r4）。"""
    words = [
        Word("ああどうも。隣の山本さん、昨日退院したんだってね", 0.0, 4.8, "1"),
        Word("失礼しまーす、315室です", 5.4, 7.0, "2"),
        Word("猫が心配でさ", 8.0, 9.0, "1"),
        Word("お熱測りますね。36.5°Cですね", 10.0, 12.0, "2"),
    ]
    assert [u.speaker for u in utterances_from_words(words)] == [
        "patient",
        "nurse",
        "patient",
        "nurse",
    ]


def test_nurse_first_is_kept() -> None:
    words = [
        Word("302号室の田中さん、お熱測りますね", 0.0, 2.0, "1"),
        Word("お孫さんが来たんだよ", 2.5, 4.0, "2"),
    ]
    assert [u.speaker for u in utterances_from_words(words)] == ["nurse", "patient"]


def test_verify_accepts_swapped_speakers(mock_client: TestClient) -> None:
    """画面で看護師と患者を入れ替えた発言の列を /api/verify に送ると、その話者で照合し直す。"""
    body = post_text_draft(mock_client, "p302")
    swapped = [
        {**u, "speaker": {"nurse": "patient", "patient": "nurse"}.get(u["speaker"], u["speaker"])}
        for u in body["utterances"]
    ]
    res = mock_client.post(
        "/api/verify", json={"utterances": swapped, "draft": body["draft"]}, headers=HEADERS
    )
    assert res.status_code == 200
    # 患者の訴え（S）の根拠が看護師の発言になったので、話者の照合で止まる
    assert any(c["code"] == "speaker_mismatch" for c in res.json()["checks"])
    res = mock_client.post(
        "/api/verify",
        json={"utterances": body["utterances"], "draft": body["draft"]},
        headers=HEADERS,
    )
    assert not any(c["code"] == "speaker_mismatch" for c in res.json()["checks"])


# --- 費用のログ（speech_usage） ---


def _silence(seconds: float) -> PreparedAudio:
    pcm = b"\0\0" * int(seconds * 16000)
    return PreparedAudio(pcm=pcm, seconds=seconds, spans=chunk_spans(seconds))


class _SaysHai:
    """区切りごとに「はい」と返す。fail_on の区切り（何回目か）では例外を投げる。"""

    def __init__(self, fail_on: dict[int, Exception] | None = None) -> None:
        self.calls = 0
        self._fail_on = fail_on or {}

    def recognize(self, request: Any, timeout: float) -> Any:
        self.calls += 1
        if self.calls in self._fail_on:
            raise self._fail_on[self.calls]
        word = NS(word="はい", start_offset=timedelta(seconds=1), end_offset=timedelta(seconds=1.5), speaker_label="1")  # fmt: skip
        return NS(results=[NS(alternatives=[NS(words=[word], transcript="はい")], result_end_offset=timedelta(seconds=2))])  # fmt: skip


def _usage(caplog: pytest.LogCaptureFixture) -> dict[str, Any]:
    entries = [json.loads(r.message) for r in caplog.records if "speech_usage" in r.message]
    assert len(entries) == 1
    return entries[0]


@needs_ffmpeg
def test_speech_usage_is_logged_per_recording(caplog: pytest.LogCaptureFixture) -> None:
    """区切りの数・送った秒・課金の秒（1回ごとに1秒単位で切り上げ）・見込みの額を出す。"""
    speech = GoogleSpeech("p", "us", "chirp_3", client=_SaysHai())
    with caplog.at_level(logging.INFO):
        speech.transcribe(_silence(62.5))
    usage = _usage(caplog)
    assert usage["severity"] == "INFO"
    assert (usage["model"], usage["location"], usage["pieces"]) == ("chirp_3", "us", 2)
    assert usage["sent_seconds"] == 67.5  # 0〜55秒と 50〜62.5秒（5秒の重なりも送る）
    assert usage["billed_seconds"] == 55 + 13
    assert usage["usd"] == pytest.approx(68 / 60 * 0.016, abs=1e-6)
    assert "はい" not in caplog.text  # 会話の文は出さない（P-04）


@needs_ffmpeg
def test_failed_pieces_are_counted_if_they_may_be_billed(caplog: pytest.LogCaptureFixture) -> None:
    """4xx（入力・権限の誤り）は数えず、時間切れなどは課金されうるので数える。失敗は投げ直す。"""
    from google.api_core import exceptions

    fail = {1: exceptions.InvalidArgument("60秒超"), 2: exceptions.DeadlineExceeded("時間切れ")}
    speech = GoogleSpeech("p", "us", "chirp_3", client=_SaysHai(fail))
    with caplog.at_level(logging.INFO), pytest.raises(exceptions.GoogleAPICallError):
        speech.transcribe(_silence(62.5))
    usage = _usage(caplog)
    assert usage["severity"] == "WARNING"
    assert usage["failed_pieces"] == 2
    assert sorted(usage["error_types"]) == ["DeadlineExceeded", "InvalidArgument"]
    assert usage["billed_seconds"] in (13, 55)  # 並べて呼ぶので、どちらが先に失敗するかは決まらない


@needs_ffmpeg
def test_unpriced_speech_model_is_warned(caplog: pytest.LogCaptureFixture) -> None:
    speech = GoogleSpeech("p", "us", "chirp_9", client=_SaysHai())
    with caplog.at_level(logging.INFO):
        speech.transcribe(_silence(10.0))
    usage = _usage(caplog)
    assert usage["severity"] == "WARNING" and usage["usd"] is None
    assert "単価を確かめていない" in usage["message"]


def test_billed_seconds_round_up_per_call() -> None:
    assert [billed_seconds(s) for s in (0.2, 12.5, 55.0)] == [1, 13, 55]
