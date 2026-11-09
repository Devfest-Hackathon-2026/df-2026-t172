"""GET /api/nurses 看護師の一覧（架空、決まり S-08）。"""

from fastapi import APIRouter, Depends

from app.config import Settings
from app.container import Services
from app.models.nurse import NursesResponse
from app.routes.deps import services, settings

router = APIRouter()


@router.get("/api/nurses")
def list_nurses(
    svc: Services = Depends(services), cfg: Settings = Depends(settings)
) -> NursesResponse:
    """タスクの担当に選べる看護師（デモは架空の数人）。"""
    return NursesResponse(mode=cfg.mode, nurses=svc.nurses)
