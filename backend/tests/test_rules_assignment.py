"""S-08：タスクの担当の割り振り（ログインなし）。

看護師は架空の数人。タスクは作ったときに患者の受け持ちを担当にし、看護師が
「担当に回す」「自分で引き取る」で変えられる。誰が変えたかはログインがないので残せない。
"""

from typing import Any

import pytest
from fastapi.testclient import TestClient

from app.services.mock_data import load_nurses
from tests.helpers import HEADERS, ROSTER, post_text_draft, record_body


def _open_tasks(client: TestClient, **params: str) -> list[dict[str, Any]]:
    res = client.get("/api/tasks", params=params, headers=HEADERS)
    assert res.status_code == 200, res.text
    return res.json()["tasks"]


def _patch(client: TestClient, task_id: str, body: dict[str, Any]) -> Any:
    return client.patch(f"/api/tasks/{task_id}", json=body, headers=HEADERS)


def test_S08_nurses_are_fictional_list_from_seed(mock_client: TestClient) -> None:
    """S-08・P-07：看護師の一覧は seed の架空の人で、id・名前・かなだけを返す。"""
    nurses = mock_client.get("/api/nurses", headers=HEADERS).json()["nurses"]
    assert nurses == [n.model_dump() for n in load_nurses()]
    assert len(nurses) >= 2 and all(set(n) == {"id", "name", "kana"} for n in nurses)


def test_S08_nurses_need_passcode(mock_client: TestClient) -> None:
    """S-08：看護師の一覧も、ほかの API と同じく合言葉がないと 401。"""
    assert mock_client.get("/api/nurses").status_code == 401


def test_S08_every_patient_has_a_listed_nurse() -> None:
    """S-08：名簿の全員に、看護師の一覧にいる受け持ちがいる。"""
    nurse_ids = {n.id for n in load_nurses()}
    assert all(p.assigned_to in nurse_ids for p in ROSTER)


def test_S08_confirmed_tasks_go_to_the_patients_nurse(mock_client: TestClient) -> None:
    """S-08：確定から作るタスクは、その患者の受け持ちが担当で、assigned_set_by は rule。"""
    draft = post_text_draft(mock_client, "p305")
    res = mock_client.post("/api/records", json=record_body(draft), headers=HEADERS)
    created = set(res.json()["tasks_created"])
    tasks = [t for t in _open_tasks(mock_client) if t["id"] in created]
    assert len(tasks) == len(created) > 0
    assert {(t["assigned_to"], t["assigned_set_by"]) for t in tasks} == {("n02", "rule")}


def test_S08_manual_task_goes_to_the_patients_nurse(mock_client: TestClient) -> None:
    """S-08：POST /api/tasks のタスクも、その患者の受け持ちが担当になる。"""
    body = {"patient_id": "p310", "text": "家族に電話"}
    task = mock_client.post("/api/tasks", json=body, headers=HEADERS).json()["task"]
    assert (task["assigned_to"], task["assigned_set_by"]) == ("n03", "rule")


def test_S08_demo_tasks_have_the_patients_nurse(mock_client: TestClient) -> None:
    """S-08：モックの見本タスクにも、患者の受け持ちが担当として入っている。"""
    nurse_of = {p.id: p.assigned_to for p in ROSTER}
    tasks = _open_tasks(mock_client)
    assert tasks and all(t["assigned_to"] == nurse_of[t["patient_id"]] for t in tasks)


@pytest.mark.parametrize("nurse_id", ["n04", "n01"])
def test_S08_nurse_reassigns_a_task(mock_client: TestClient, nurse_id: str) -> None:
    """S-08：担当に回す・自分で引き取ると担当が変わり、assigned_set_by が nurse になる。"""
    res = _patch(mock_client, "t_demo2", {"assigned_to": nurse_id})
    assert res.status_code == 200, res.text
    task = res.json()["task"]
    assert (task["assigned_to"], task["assigned_set_by"]) == (nurse_id, "nurse")
    assert task["status"] == "open" and task["urgency_set_by"] == "rule"  # ほかは変わらない


@pytest.mark.parametrize("nurse_id", ["n99", "../n01", ""])
def test_S08_unknown_nurse_is_422(mock_client: TestClient, nurse_id: str) -> None:
    """S-08：一覧にない看護師・形の誤った id は 422 で、担当は変わらない。"""
    before = next(t for t in _open_tasks(mock_client) if t["id"] == "t_demo2")
    res = _patch(mock_client, "t_demo2", {"assigned_to": nurse_id})
    assert res.status_code == 422
    after = next(t for t in _open_tasks(mock_client) if t["id"] == "t_demo2")
    assert after["assigned_to"] == before["assigned_to"]


def test_S08_unknown_nurse_error_code(mock_client: TestClient) -> None:
    """S-08：一覧にない看護師は unknown_nurse で返す（画面が言葉を出し分けられるように）。"""
    res = _patch(mock_client, "t_demo2", {"assigned_to": "n99"})
    assert res.json()["error"]["code"] == "unknown_nurse"


def test_S08_filter_tasks_by_nurse(mock_client: TestClient) -> None:
    """S-08：GET /api/tasks?assigned_to= で、その看護師が担当のタスクだけになる。"""
    everyone = _open_tasks(mock_client)
    _patch(mock_client, everyone[0]["id"], {"assigned_to": "n04"})
    mine = _open_tasks(mock_client, assigned_to="n04")
    assert [t["id"] for t in mine] == [everyone[0]["id"]]
    assert _open_tasks(mock_client, assigned_to="n99") == []
    bad = mock_client.get("/api/tasks", params={"assigned_to": "a b"}, headers=HEADERS)
    assert bad.status_code == 422


def test_S08_clients_that_do_not_send_assignment_still_work(mock_client: TestClient) -> None:
    """S-08：assigned_to を送らない今の画面の PATCH も動き、担当はそのまま残る。"""
    _patch(mock_client, "t_demo3", {"assigned_to": "n04"})
    task = _patch(mock_client, "t_demo3", {"status": "done"}).json()["task"]
    assert (task["status"], task["assigned_to"], task["assigned_set_by"]) == (
        "done",
        "n04",
        "nurse",
    )
