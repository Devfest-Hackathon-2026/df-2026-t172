"""GET /api/records・GET /api/records/{id} 保存した記録を見る（会話記録の画面）。

期限切れ（翌日0時を過ぎたもの）は返さない。TTL の削除は最大で1日ほど遅れるので、
読むときにも期限で除く（P-03）。結果として当日分だけになる。
"""

from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends, Path, Query

from app.config import Settings
from app.container import Services
from app.errors import ApiError
from app.models.api import Patient
from app.models.draft import Draft
from app.models.limits import ID_PATTERN
from app.models.record_views import (
    PREVIEW_CHARS,
    RecordDetail,
    RecordDetailResponse,
    RecordsResponse,
    RecordSummary,
)
from app.routes.deps import services, settings
from app.services.chart import chart_text
from app.services.clock import iso, now_jst
from app.store.base import Document

router = APIRouter()

MAX_RECORDS = 100
# 記録の id は r_{患者の id}_{確定の id}（app.services.confirm）
RECORD_ID_PATTERN = r"^r_[A-Za-z0-9_-]{1,90}$"


def _preview(sentences: list[Document]) -> str | None:
    return sentences[0]["text"][:PREVIEW_CHARS] if sentences else None


def _summary(doc: Document) -> RecordSummary:
    return RecordSummary(
        record_id=doc["id"],
        patient_id=doc["patient_id"],
        room=doc["room"],
        name=doc["name"],
        full_name=doc.get("full_name", ""),
        created_at=iso(doc["created_at"]),
        s_preview=_preview(doc["soap"]["S"]),
        o_preview=_preview(doc["soap"]["O"]),
        request_count=len(doc["requests"]),
    )


def _patient_of(svc: Services, doc: Document) -> Patient:
    """カルテ用の文の先頭に使う患者。名簿にいなければ、記録に残した部屋と名前で作る。"""
    found = next((p for p in svc.roster if p.id == doc["patient_id"]), None)
    return found or Patient(
        id=doc["patient_id"],
        room=doc["room"],
        bed="",
        name=doc["name"],
        kana="",
        full_name=doc.get("full_name", ""),
    )


def _detail(svc: Services, doc: Document) -> RecordDetail:
    draft = Draft.model_validate(doc)
    created_at: datetime = doc["created_at"]
    return RecordDetail.model_validate(
        {
            **doc,
            "record_id": doc["id"],
            "created_at": iso(created_at),
            "chart_text": chart_text(_patient_of(svc, doc), draft, created_at),
        }
    )


@router.get("/api/records")
def list_records(
    patient_id: Annotated[str | None, Query(pattern=ID_PATTERN)] = None,
    svc: Services = Depends(services),
    cfg: Settings = Depends(settings),
) -> RecordsResponse:
    """保存した記録の一覧（新しい順、100件まで）。patient_id がなければ病棟の全員。"""
    docs = svc.store.list_records(patient_id, now_jst())
    docs.sort(key=lambda d: d["created_at"], reverse=True)
    return RecordsResponse(mode=cfg.mode, records=[_summary(d) for d in docs[:MAX_RECORDS]])


@router.get("/api/records/{record_id}")
def get_record(
    record_id: Annotated[str, Path(pattern=RECORD_ID_PATTERN)],
    svc: Services = Depends(services),
    cfg: Settings = Depends(settings),
) -> RecordDetailResponse:
    """保存した記録の全体と、作り直したカルテ用の文。会話の全文は返さない（保存していない）。"""
    doc = svc.store.get_record(record_id, now_jst())
    if doc is None:
        raise ApiError(
            404, "record_not_found", "記録が見つかりません（期限切れで消えた可能性があります）"
        )
    return RecordDetailResponse(mode=cfg.mode, record=_detail(svc, doc))
