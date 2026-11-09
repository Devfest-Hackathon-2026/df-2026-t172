"""S-08：患者の受け持ちをその日に変える（ログインなし）。

受け持ちを変えると、担当を人が変えていない（rule）未完了のタスクも一緒に移る。
看護師が回した・引き取ったタスクと、済みのタスクは動かさない。
"""

from datetime import timedelta
from typing import Any

import pytest
from fastapi.testclient import TestClient

from app.services.clock import now_jst
from app.store.firestore_store import FirestoreStore
from tests.helpers import HEADERS, ROSTER, post_text_draft, record_body
from tests.test_live_clients import FakeFirestore


def _change(client: TestClient, patient_id: str, nurse_id: str) -> Any:
    return client.patch(
        f"/api/patients/{patient_id}", json={"assigned_to": nurse_id}, headers=HEADERS
    )


def _tasks_of(client: TestClient, patient_id: str) -> dict[str, dict[str, Any]]:
    tasks = client.get("/api/tasks", params={"status": "all"}, headers=HEADERS).json()["tasks"]
    return {t["id"]: t for t in tasks if t["patient_id"] == patient_id}


def test_S08_change_assignee_moves_rule_tasks(mock_client: TestClient) -> None:
    """S-08：受け持ちを変えると名簿に出て、受け持ちから写しただけのタスクも移る。"""
    res = _change(mock_client, "p305", "n04")
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["patient"]["assigned_to"] == "n04"
    assert body["tasks_moved"] and set(body["tasks_moved"]) == set(_tasks_of(mock_client, "p305"))
    patients = mock_client.get("/api/patients", headers=HEADERS).json()["patients"]
    assert next(p for p in patients if p["id"] == "p305")["assigned_to"] == "n04"
    assert {t["assigned_to"] for t in _tasks_of(mock_client, "p305").values()} == {"n04"}


def test_S08_nurse_choices_and_done_tasks_stay(mock_client: TestClient) -> None:
    """S-08：看護師が回したタスク（nurse）と済みのタスクは、受け持ちを変えても動かない。"""
    reassigned, done = sorted(_tasks_of(mock_client, "p305"))[:2]
    mock_client.patch(f"/api/tasks/{reassigned}", json={"assigned_to": "n01"}, headers=HEADERS)
    mock_client.patch(f"/api/tasks/{done}", json={"status": "done"}, headers=HEADERS)
    moved = _change(mock_client, "p305", "n04").json()["tasks_moved"]
    assert reassigned not in moved and done not in moved
    tasks = _tasks_of(mock_client, "p305")
    assert tasks[reassigned]["assigned_to"] == "n01"
    assert tasks[done]["assigned_to"] == "n02"  # 済みは元の担当のまま


def test_S08_new_tasks_use_the_changed_assignee(mock_client: TestClient) -> None:
    """S-08：変えた後に作るタスクは、確定からでも直接でも、新しい受け持ちが担当。"""
    _change(mock_client, "p302", "n03")
    direct = mock_client.post(
        "/api/tasks", json={"patient_id": "p302", "text": "家族に電話"}, headers=HEADERS
    ).json()["task"]
    draft = post_text_draft(mock_client, "p302")
    created = mock_client.post("/api/records", json=record_body(draft), headers=HEADERS).json()
    tasks = _tasks_of(mock_client, "p302")
    assert direct["assigned_to"] == "n03"
    assert {tasks[i]["assigned_to"] for i in created["tasks_created"]} == {"n03"}


@pytest.mark.parametrize(
    ("patient_id", "nurse_id", "status"),
    [("p305", "n99", 422), ("p999", "n01", 404), ("p305", "a b", 422)],
)
def test_S08_bad_assignee_change_is_rejected(
    mock_client: TestClient, patient_id: str, nurse_id: str, status: int
) -> None:
    """S-08：一覧にない看護師・形の誤った id は 422、名簿にない患者は 404。受け持ちは変わらない。"""
    assert _change(mock_client, patient_id, nurse_id).status_code == status
    patients = mock_client.get("/api/patients", headers=HEADERS).json()["patients"]
    assert next(p for p in patients if p["id"] == "p305")["assigned_to"] == "n02"


def test_S08_restart_keeps_changed_assignee_in_firestore() -> None:
    """S-08：live で再起動して名簿を入れ直しても、画面で変えた受け持ちは seed に戻らない。"""
    db = FakeFirestore()
    store = FirestoreStore(db)
    store.seed_patients(ROSTER)
    store.set_patient_assignee("p302", "n04", "n02")
    store.seed_patients(ROSTER)  # 再起動
    kept = store.get_patient("p302")
    assert (kept.assigned_to, kept.assigned_reported_by) == ("n04", "n02")  # type: ignore[union-attr]
    assert store.get_patient("p303").assigned_to == "n01"  # type: ignore[union-attr]


def test_S08_old_null_assignee_in_firestore_takes_seed() -> None:
    """S-08：前の版で null のまま入っている受け持ちは、seed の値で埋める。"""
    db = FakeFirestore()
    store = FirestoreStore(db)
    store.seed_patients([p.model_copy(update={"assigned_to": None}) for p in ROSTER])
    store.seed_patients(ROSTER)
    assert store.get_patient("p302").assigned_to == "n01"  # type: ignore[union-attr]


def test_S08_firestore_moves_only_open_rule_tasks() -> None:
    """S-08：Firestore でも、未完了・期限内・rule のタスクだけを移す。"""
    store = FirestoreStore(FakeFirestore())
    now = now_jst()
    base = {"patient_id": "p302", "status": "open", "urgency": "none", "assigned_to": "n01"}
    later = now + timedelta(hours=1)
    tasks = [
        {**base, "id": "t_rule", "assigned_set_by": "rule", "expires_at": later},
        {**base, "id": "t_old", "expires_at": later},  # 前からある（set_by なし）
        {**base, "id": "t_nurse", "assigned_set_by": "nurse", "expires_at": later},
        {**base, "id": "t_done", "status": "done", "assigned_set_by": "rule", "expires_at": later},
        {**base, "id": "t_gone", "assigned_set_by": "rule", "expires_at": now},
        {**base, "id": "t_other", "patient_id": "p303", "expires_at": later},
    ]
    for task in tasks:
        store.add_task(task)
    assert sorted(store.move_rule_tasks("p302", "n04", now)) == ["t_old", "t_rule"]
    moved_now = [t["id"] for t in store.list_tasks("open", now) if t["assigned_to"] == "n04"]
    assert sorted(moved_now) == ["t_old", "t_rule"]
