"""POST /api/verify 照合だけやり直す（状態を持たない）。"""

from fastapi import APIRouter, Depends, Request

from app.config import Settings
from app.container import Services
from app.models.api import VerifyRequest, VerifyResponse
from app.routes.deps import client_key, services, settings
from app.services.drafting import check_draft
from app.services.nurse_added import ensure_nurse_evidence_exists

router = APIRouter()


@router.post("/api/verify")
def verify_draft(
    body: VerifyRequest,
    request: Request,
    svc: Services = Depends(services),
    cfg: Settings = Depends(settings),
) -> VerifyResponse:
    """看護師が下書きを直したとき・手でバイタルを入れたときに呼ぶ。

    entail=true なら二段目の確認もかけ直し（live では Gemini を1回呼ぶ）、署名つきの
    判定を返す。entail=false はコードの照合だけで、有料の呼び出しの回数も数えない。
    """
    ensure_nurse_evidence_exists(body.draft, body.utterances)
    gemini = None
    if body.entail:
        if cfg.mode == "live":
            svc.call_limit.take(1, client_key(request))
        gemini = svc.gemini
    checked = check_draft(body.draft, body.utterances, gemini, svc.sealer)
    return VerifyResponse(
        mode=cfg.mode, checks=checked.checks, missing=checked.missing, entail_seals=checked.seals
    )
