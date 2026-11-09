"""POST /api/drafts 下書きを作る（保存しない）。

入力は2通り：multipart の音声（patient_id・audio・consent_confirmed）か、JSON の
テキスト（patient_id・transcript）。どちらも同じ URL で受け、Content-Type で分ける。
Gemini や Speech-to-Text が失敗しても、モックの結果には切り替えない（C-05）。

入力の読み取りだけを async で行い、音声・Gemini の同期の呼び出しはスレッドで動かす
（イベントループを止めて、ほかの人の操作まで待たせないため）。
"""

from fastapi import APIRouter, Depends, Request
from starlette.concurrency import run_in_threadpool

from app.checks.patient_match import match_patient
from app.config import Settings
from app.container import Services
from app.errors import ApiError
from app.live.audio_flac import AudioUnreadable
from app.live.interfaces import PreparedAudio
from app.models.api import DraftResponse, Patient
from app.models.draft import Utterance
from app.models.limits import MAX_UTTERANCES
from app.routes.deps import client_key, find_patient, services, settings, with_current_assignee
from app.routes.draft_input import DraftInput, audio_too_long, read_draft_input
from app.services.drafting import build_draft, run_entail
from app.services.first_speaker import apply_to_audio, apply_to_text
from app.services.mock_data import load_mock_draft, scenario_for_patient
from app.services.safe_log import log_failure
from app.services.transcript import parse_transcript

router = APIRouter()

# 1回の下書きで呼ぶ有料の呼び出しの最大の数（① 下書き ② 二段目）。音声なら、これに
# 文字起こしの区切りの数（55秒ごと、3分で4つ）を足す。二段目にかける文がなければ
# 実際は1回少ないが、上限の数え方は多めでよい
CALLS_FOR_TEXT = 2


def _mock_response(svc: Services, patient: Patient, input_kind: str) -> DraftResponse:
    """場面の見本を返す。患者の照合と二段目の署名は、その場で付け直す。"""
    response = load_mock_draft(scenario_for_patient(patient.id))
    _, seals = run_entail(response.draft, response.utterances, svc.gemini, svc.sealer)
    return response.model_copy(
        update={
            "patient": patient,
            "patient_match": match_patient(patient, svc.roster, response.utterances),
            "input": input_kind,
            "entail_seals": seals,
        }
    )


def _prepare_audio(svc: Services, cfg: Settings, audio: bytes) -> PreparedAudio:
    """音声を読み、長さを確かめる（認識の前。費用はかからない）。"""
    if svc.speech is None:
        raise ApiError(
            503, "speech_unavailable", "音声の文字起こしが使えません。テキストで入力してください"
        )
    try:
        prepared = svc.speech.prepare(audio)
    except AudioUnreadable as e:
        raise ApiError(
            422, "audio_unreadable", "録音を読み取れませんでした。もう一度録音してください"
        ) from e
    except Exception as e:
        log_failure("speech_failed", e)
        raise ApiError(
            502, "speech_failed", "文字起こしに失敗しました。テキストで入力してください"
        ) from e
    if prepared.seconds > cfg.max_audio_seconds:
        raise audio_too_long(cfg)
    return prepared


def _transcribe(svc: Services, cfg: Settings, prepared: PreparedAudio) -> list[Utterance]:
    """音声を発言の列にする。音声はここで使い終わり、どこにも保存しない（P-01）。"""
    assert svc.speech is not None  # _prepare_audio で確かめ済み
    try:
        utterances = svc.speech.transcribe(prepared)
    except Exception as e:
        log_failure("speech_failed", e)
        raise ApiError(
            502, "speech_failed", "文字起こしに失敗しました。テキストで入力してください"
        ) from e
    last_end = max((u.end or 0.0 for u in utterances), default=0.0)
    if last_end > cfg.max_audio_seconds:
        raise audio_too_long(cfg)
    return utterances


def _utterances(
    svc: Services, cfg: Settings, given: DraftInput, prepared: PreparedAudio | None
) -> list[Utterance]:
    """入力を発言の列にする。空・多すぎる（SEC-04）なら止める。"""
    # 最初に話す人の指定は、Gemini に下書きを作らせる前に当てる（app.services.first_speaker）
    if prepared is not None:
        utterances = apply_to_audio(_transcribe(svc, cfg, prepared), given.first_speaker)
    else:
        utterances = apply_to_text(parse_transcript(given.transcript or ""), given.first_speaker)
    if not utterances:
        raise ApiError(
            422, "empty_conversation", "会話が聞き取れませんでした。もう一度録音してください"
        )
    if len(utterances) > MAX_UTTERANCES:
        raise ApiError(
            413, "too_many_utterances", f"発言は{MAX_UTTERANCES}個までです。短く区切ってください"
        )
    return utterances


def _live_draft(
    svc: Services,
    cfg: Settings,
    given: DraftInput,
    prepared: PreparedAudio | None,
    patient: Patient,
) -> DraftResponse:
    """文字起こし（音声なら）→ 下書き → 照合 → 二段目。Gemini の失敗は 502 にする。"""
    utterances = _utterances(svc, cfg, given, prepared)
    try:
        return build_draft(
            mode=cfg.mode,
            patient=patient,
            roster=svc.roster,
            utterances=utterances,
            input_kind="audio" if given.audio is not None else "text",
            gemini=svc.gemini,
            sealer=svc.sealer,
        )
    except Exception as e:
        log_failure("draft_failed", e)
        raise ApiError(
            502, "draft_failed", "下書きを作れませんでした。もう一度お試しください"
        ) from e


def make_draft(svc: Services, cfg: Settings, given: DraftInput, client: str) -> DraftResponse:
    """下書きを作る（同期。スレッドで呼ぶ）。失敗したら、数えた回数を戻す。"""
    patient = with_current_assignee(svc, find_patient(svc, given.patient_id))
    if cfg.mode == "mock":
        return _mock_response(svc, patient, "audio" if given.audio is not None else "text")
    prepared = _prepare_audio(svc, cfg, given.audio) if given.audio is not None else None
    calls = CALLS_FOR_TEXT + (prepared.calls if prepared else 0)
    svc.call_limit.take(calls, client)
    try:
        return _live_draft(svc, cfg, given, prepared, patient)
    except Exception:
        svc.call_limit.give_back(calls, client)
        raise


@router.post("/api/drafts")
async def create_draft(
    request: Request, svc: Services = Depends(services), cfg: Settings = Depends(settings)
) -> DraftResponse:
    """音声かテキストと、選んだ患者から、下書き・照合の結果・患者の照合を返す。"""
    given = await read_draft_input(request, cfg)
    response = await run_in_threadpool(make_draft, svc, cfg, given, client_key(request))
    # AI が書いた要素の印。確定のとき、看護師が足したと偽った要素を見分ける（A-12）
    return response.model_copy(update={"draft_token": svc.draft_tokens.issue(response.draft)})
