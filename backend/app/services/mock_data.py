"""モックの元データ・名簿・見本のタスクを読む。"""

import json
from datetime import datetime
from functools import cache
from pathlib import Path
from typing import Any

from app.config import BACKEND_DIR
from app.models.api import DraftResponse, Patient
from app.models.nurse import Nurse
from app.services.clock import expires_at

MOCK_DIR = BACKEND_DIR / "mock"
SEED_PATIENTS = BACKEND_DIR / "seed" / "patients.json"
SEED_NURSES = BACKEND_DIR / "seed" / "nurses.json"
# 元データの patient_id にない患者を選んだときに返す場面（data-model.md の 5章）
DEFAULT_SCENARIO = "s1"


def _read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def load_patients() -> list[Patient]:
    """架空の名簿（`backend/seed/patients.json`）。"""
    return [Patient.model_validate(p) for p in _read_json(SEED_PATIENTS)]


def load_nurses() -> list[Nurse]:
    """架空の看護師の一覧（`backend/seed/nurses.json`、S-08）。"""
    return [Nurse.model_validate(n) for n in _read_json(SEED_NURSES)]


@cache
def load_scenarios() -> tuple[dict[str, Any], ...]:
    """モックの元データ（場面ごとの会話・下書きの見本・期待値）。"""
    return tuple(_read_json(MOCK_DIR / "source" / "scenarios.json")["scenarios"])


def scenario_for_patient(patient_id: str) -> str:
    """選んだ患者に対応する場面の id。"""
    by_patient = {sc["patient_id"]: sc["id"] for sc in load_scenarios()}
    return by_patient.get(patient_id, DEFAULT_SCENARIO)


def mock_draft_path(scenario_id: str) -> Path:
    """モック JSON の場所（`backend/mock/draft_s1.json` など）。"""
    return MOCK_DIR / f"draft_{scenario_id}.json"


def load_mock_draft(scenario_id: str) -> DraftResponse:
    """モック JSON を読む。"""
    return DraftResponse.model_validate(_read_json(mock_draft_path(scenario_id)))


def load_demo_tasks(now: datetime) -> list[dict[str, Any]]:
    """タスク画面の見本（3段がそろうように作った架空の依頼）。時刻は今日にする。

    担当は、確定から作るタスクと同じく、患者の受け持ちを写す（S-08）。
    """
    tasks = _read_json(MOCK_DIR / "tasks.json")["tasks"]
    assigned = {p.id: p.assigned_to for p in load_patients()}
    return [
        {
            **{k: v for k, v in t.items() if k != "hour"},
            "record_id": None,
            "assigned_to": assigned.get(t["patient_id"]),
            "assigned_set_by": "rule",
            "created_at": now.replace(hour=t["hour"], minute=0, second=0, microsecond=0),
            "done_at": None,
            "expires_at": expires_at(now),
        }
        for t in tasks
    ]
