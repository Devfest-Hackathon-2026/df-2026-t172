"""POST /api/drafts の入力を読み、決まりに合わない入力をここで止める。

- O-01：音声は、録音の前に患者の同意を確かめたこと（consent_confirmed=true）が要る。なければ 400
- SEC-04：音声は3分・10MB まで、テキストは5,000文字までで、超えたら 413
  （本文の大きさそのものは、先に app.middleware.body_limit が見ている）
"""

import re
from dataclasses import dataclass

from fastapi import Request
from pydantic import ValidationError
from starlette.datastructures import UploadFile

from app.config import Settings
from app.errors import ApiError
from app.models.api import TextDraftRequest
from app.models.draft import FirstSpeaker
from app.models.limits import ID_PATTERN


@dataclass(frozen=True)
class DraftInput:
    """下書きの入力。audio と transcript のどちらか一方だけが入る。"""

    patient_id: str
    audio: bytes | None = None
    transcript: str | None = None
    first_speaker: FirstSpeaker = "auto"


def audio_too_long(cfg: Settings) -> ApiError:
    """録音が長すぎるときのエラー（413）。"""
    minutes = cfg.max_audio_seconds / 60
    return ApiError(413, "audio_too_long", f"録音は{minutes:g}分までです。短く区切ってください")


async def _read_audio_form(request: Request, cfg: Settings) -> DraftInput:
    form = await request.form()
    patient_id, audio = form.get("patient_id"), form.get("audio")
    if not isinstance(patient_id, str) or not isinstance(audio, UploadFile):
        raise ApiError(422, "invalid_request", "patient_id と audio を送ってください")
    if not re.fullmatch(ID_PATTERN, patient_id):
        raise ApiError(422, "invalid_request", "patient_id の形が正しくありません")
    if form.get("consent_confirmed") != "true":
        raise ApiError(400, "consent_required", "録音の前に、患者さんの同意を確かめてください")
    # 録音の長さは画面（MediaRecorder）が知っている。送られなければ文字起こしの後に確かめる
    duration = form.get("duration_seconds")
    if isinstance(duration, str) and duration:
        try:
            seconds = float(duration)
        except ValueError as e:
            raise ApiError(
                422, "invalid_request", "duration_seconds は秒の数で送ってください"
            ) from e
        if seconds > cfg.max_audio_seconds:
            raise audio_too_long(cfg)
    first_speaker = form.get("first_speaker") or "auto"
    if first_speaker not in ("nurse", "patient", "auto"):
        raise ApiError(422, "invalid_request", "first_speaker は nurse・patient・auto のどれかです")
    data = await audio.read(cfg.max_audio_bytes + 1)
    if len(data) > cfg.max_audio_bytes:
        raise ApiError(413, "audio_too_large", "録音のファイルが大きすぎます（10MB まで）")
    return DraftInput(patient_id=patient_id, audio=data, first_speaker=first_speaker)


async def _read_text_json(request: Request, cfg: Settings) -> DraftInput:
    try:
        body = TextDraftRequest.model_validate(await request.json())
    except (ValueError, ValidationError) as e:
        raise ApiError(422, "invalid_request", "patient_id と transcript を送ってください") from e
    if len(body.transcript) > cfg.max_transcript_chars:
        raise ApiError(
            413,
            "transcript_too_long",
            f"テキストは{cfg.max_transcript_chars:,}文字までです",
        )
    return DraftInput(
        patient_id=body.patient_id, transcript=body.transcript, first_speaker=body.first_speaker
    )


async def read_draft_input(request: Request, cfg: Settings) -> DraftInput:
    """multipart なら音声、そうでなければ JSON のテキストとして読む。

    Raises:
        ApiError: 同意がない（400）、大きすぎる（413）、形が違う（422）場合
    """
    if request.headers.get("content-type", "").startswith("multipart/form-data"):
        return await _read_audio_form(request, cfg)
    return await _read_text_json(request, cfg)
