"""GET /api/patients 名簿・PATCH /api/patients/{id} 受け持ちを変える（S-08）。"""

from typing import Annotated

from fastapi import APIRouter, Depends, Path

from app.config import Settings
from app.container import Services
from app.errors import ApiError
from app.models.api import PatientAssigneePatch, PatientAssigneeResponse, PatientsResponse
from app.models.limits import ID_PATTERN
from app.routes.deps import ensure_known_nurse, ensure_reported_by, services, settings
from app.services.clock import now_jst
from app.services.safe_log import log_event

router = APIRouter()


@router.get("/api/patients")
def list_patients(
    svc: Services = Depends(services), cfg: Settings = Depends(settings)
) -> PatientsResponse:
    """今日の名簿（デモは架空）。受け持ちは画面で変わるので、保存先の今の値を返す。"""
    return PatientsResponse(mode=cfg.mode, patients=svc.store.list_patients())


@router.patch("/api/patients/{patient_id}")
def change_assignee(
    patient_id: Annotated[str, Path(pattern=ID_PATTERN)],
    body: PatientAssigneePatch,
    svc: Services = Depends(services),
    cfg: Settings = Depends(settings),
) -> PatientAssigneeResponse:
    """患者の基本の受け持ちを変える（その日の入れ替え）。

    担当を人が変えていない（rule）未完了のタスクも、新しい受け持ちに移す。ログインが
    ないので、誰が変えたかは画面で選んだ「自分」の自己申告（reported_by）だけを残す（S-08）。
    """
    ensure_known_nurse(svc, body.assigned_to)
    ensure_reported_by(svc, body.reported_by)
    patient = svc.store.set_patient_assignee(patient_id, body.assigned_to, body.reported_by)
    if patient is None:
        raise ApiError(404, "patient_not_found", "名簿にない患者です。選び直してください")
    moved = svc.store.move_rule_tasks(patient_id, body.assigned_to, now_jst())
    # 計測用（P-04：患者名は出さない。数だけ）
    log_event(
        "patient_assignee_changed",
        assigned_to=body.assigned_to,
        reported_by=body.reported_by,
        tasks_moved=len(moved),
    )
    return PatientAssigneeResponse(mode=cfg.mode, patient=patient, tasks_moved=moved)
