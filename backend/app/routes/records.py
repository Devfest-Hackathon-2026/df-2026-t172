"""POST /api/records 確定する。"""

from fastapi import APIRouter, Depends, Request

from app.config import Settings
from app.container import Services
from app.errors import ApiError
from app.live.interfaces import GeminiClient
from app.models.api import RecordResponse
from app.models.record_request import RecordRequest
from app.routes.deps import (
    client_key,
    ensure_reported_by,
    find_patient,
    services,
    settings,
    with_current_assignee,
)
from app.services.clock import now_jst
from app.services.confirm import confirm_record
from app.services.drafting import EntailRecheck, recheck_entail
from app.services.nurse_added import ensure_nurse_evidence_exists, relabel_ai_elements
from app.services.safe_log import log_event

router = APIRouter()


def _gemini_within_limit(svc: Services, cfg: Settings, client: str) -> GeminiClient | None:
    """二段目の呼び直しに使う Gemini。今日の上限なら None（呼ばずに止める）。"""
    if cfg.mode == "live":
        try:
            svc.call_limit.take(1, client)
        except ApiError:
            # 上限で確定そのものは止めない。裏付けのない文を「判断できない」で止める
            log_event("entail_recheck_skipped", reason="daily_limit")
            return None
    return svc.gemini


@router.post("/api/records")
def create_record(
    body: RecordRequest,
    request: Request,
    svc: Services = Depends(services),
    cfg: Settings = Depends(settings),
) -> RecordResponse:
    """確定した記録とタスクを保存し、カルテ用の文を返す（会話の文の全体は保存しない）。

    二段目の結果は署名（entail_seals）で裏付けられたものだけを使い、裏付けのない文は
    ここで二段目を呼び直す（A-04・A-05 をサーバーで強制する）。
    """
    # 受け持ちは画面で変わるので、タスクの担当には今の受け持ちを使う（S-08）
    patient = with_current_assignee(svc, find_patient(svc, body.patient_id))
    ensure_reported_by(svc, body.reported_by)
    client = client_key(request)
    # 下書きにあった文なのに「看護師が足した」になっている要素は AI の要素に戻す（A-12）
    fingerprints = svc.draft_tokens.ai_fingerprints(body.draft_token)
    draft, relabelled = relabel_ai_elements(body.draft, fingerprints)
    ensure_nurse_evidence_exists(draft, body.utterances)
    body = body.model_copy(update={"draft": draft})

    def judge_entail() -> EntailRecheck:
        return recheck_entail(
            body.draft,
            body.utterances,
            body.entail_seals,
            svc.sealer,
            lambda: _gemini_within_limit(svc, cfg, client),
        )

    confirmed = confirm_record(body, patient, svc.roster, now_jst(), judge_entail, relabelled)
    svc.store.save_record(confirmed.record_id, confirmed.record, confirmed.tasks)
    return RecordResponse(
        mode=cfg.mode,
        record_id=confirmed.record_id,
        chart_text=confirmed.chart_text,
        tasks_created=[t["id"] for t in confirmed.tasks],
    )
