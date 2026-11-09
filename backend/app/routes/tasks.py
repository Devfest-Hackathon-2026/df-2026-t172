"""GET /api/tasks・POST /api/tasks・PATCH /api/tasks/{id} タスク。"""

from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Path, Query

from app.config import Settings
from app.container import Services
from app.errors import ApiError
from app.models.api import Task, TaskPatch, TaskResponse, TasksResponse
from app.models.limits import ID_PATTERN
from app.models.task_create import TaskCreate
from app.routes.deps import (
    ensure_known_nurse,
    ensure_reported_by,
    find_patient,
    services,
    settings,
    with_current_assignee,
)
from app.services.clock import iso, now_jst
from app.services.manual_task import manual_task_document
from app.services.safe_log import log_event
from app.store.base import Document

router = APIRouter()

_URGENCY_ORDER = {"said_urgent": 0, "timed": 1, "none": 2}


def to_task(doc: Document) -> Task:
    """保存した1件を、API で返す形にする（日時は文字列に）。"""
    return Task.model_validate(
        {
            **doc,
            "created_at": iso(doc["created_at"]),
            "done_at": iso(doc["done_at"]) if doc.get("done_at") else None,
        }
    )


@router.get("/api/tasks")
def list_tasks(
    status: Literal["open", "done", "all"] = "open",
    assigned_to: Annotated[str | None, Query(pattern=ID_PATTERN)] = None,
    svc: Services = Depends(services),
    cfg: Settings = Depends(settings),
) -> TasksResponse:
    """タスクの一覧。並びは緊急度（said_urgent → timed → none）→ 作った時刻の順。

    assigned_to を送ると、その看護師が担当のタスクだけにする（S-08）。
    """
    docs = svc.store.list_tasks(None if status == "all" else status, now_jst())
    if assigned_to is not None:
        docs = [d for d in docs if d.get("assigned_to") == assigned_to]
    docs.sort(key=lambda d: (_URGENCY_ORDER[d["urgency"]], d["created_at"]))
    return TasksResponse(mode=cfg.mode, tasks=[to_task(d) for d in docs])


@router.post("/api/tasks")
def create_task(
    body: TaskCreate, svc: Services = Depends(services), cfg: Settings = Depends(settings)
) -> TaskResponse:
    """看護師がタスクを直接作る（AI が拾わなかった依頼など、A-12）。記録は作らない。"""
    patient = with_current_assignee(svc, find_patient(svc, body.patient_id))
    task = manual_task_document(patient, body, now_jst())
    svc.store.add_task(task)
    return TaskResponse(mode=cfg.mode, task=to_task(task))


@router.patch("/api/tasks/{task_id}")
def update_task(
    task_id: Annotated[str, Path(pattern=ID_PATTERN)],
    body: TaskPatch,
    svc: Services = Depends(services),
    cfg: Settings = Depends(settings),
) -> TaskResponse:
    """済みにする・緊急度・ラベル・担当を変える。看護師が変えたら *_set_by を nurse にする。

    担当（assigned_to）は「担当に回す」「自分で引き取る」で変える（S-08）。ログインが
    ないので、誰が変えたかは残せない。
    """
    now = now_jst()
    fields: Document = {}
    if body.status is not None:
        fields["status"] = body.status
        fields["done_at"] = now if body.status == "done" else None
    if body.urgency is not None:
        fields["urgency"] = body.urgency
        fields["urgency_set_by"] = "nurse"
    # ラベルも、看護師が変えたら set_by を nurse にする（A-13）
    for label in ("category", "role"):
        value = getattr(body, label)
        if value is not None:
            fields[label], fields[f"{label}_set_by"] = value, "nurse"
    if body.assigned_to is not None:
        ensure_known_nurse(svc, body.assigned_to)
        ensure_reported_by(svc, body.reported_by)
        fields["assigned_to"], fields["assigned_set_by"] = body.assigned_to, "nurse"
        fields["assigned_reported_by"] = body.reported_by
    if not fields:
        raise ApiError(
            422,
            "invalid_request",
            "status・urgency・category・role・assigned_to のどれかを送ってください",
        )
    updated = svc.store.update_task(task_id, fields, now)
    if updated is None:
        raise ApiError(
            404, "task_not_found", "タスクが見つかりません（期限切れで消えた可能性があります）"
        )
    if body.assigned_to is not None:
        # 計測用（P-04：患者名・依頼の文は出さない。id だけ）
        log_event(
            "task_assignee_changed",
            task_id=task_id,
            assigned_to=body.assigned_to,
            reported_by=body.reported_by,
        )
    return TaskResponse(mode=cfg.mode, task=to_task(updated))
