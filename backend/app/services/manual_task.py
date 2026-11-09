"""看護師が直接作るタスク（POST /api/tasks、決まり A-12）。

AI の下書きを通さないので、記録はない（record_id は null）。緊急度は看護師が決めた
ものをそのまま使い、urgency_set_by は nurse にする。期限はほかのタスクと同じ翌日0時。
"""

import uuid
from datetime import datetime

from app.models.api import Patient
from app.models.task_create import TaskCreate
from app.services.clock import expires_at
from app.store.base import Document


def manual_task_document(patient: Patient, body: TaskCreate, now: datetime) -> Document:
    """Firestore の tasks の1件（確定から作るタスクと同じ形）。"""
    return {
        "id": f"t_manual_{uuid.uuid4().hex[:12]}",
        "patient_id": patient.id,
        "room": patient.room,
        "name": patient.name,
        "full_name": patient.display_name,
        "record_id": None,
        "text": body.text,
        "patient_words": body.patient_words,
        "urgency": body.urgency,
        "urgency_set_by": "nurse",
        "category": body.category,
        "role": body.role,
        "category_set_by": "nurse",
        "role_set_by": "nurse",
        "cue": body.cue.model_dump() if body.cue else None,
        "status": "open",
        "assigned_to": patient.assigned_to,  # 患者の受け持ちを写す（S-08）
        "assigned_set_by": "rule",
        "created_at": now,
        "done_at": None,
        "expires_at": expires_at(now),
    }
