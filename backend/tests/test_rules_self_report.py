"""S-08：ログインなしの落としどころ。画面で選んだ「自分」を自己申告として残す。

本人の確かめはないので「誰がやったか」の証拠にはならない。「誰がやったと言っているか」を
記録と操作記録に残し、送らない今の画面もそのまま動くことを確かめる。
"""

import json
from typing import Any

import pytest
from fastapi.testclient import TestClient

from tests.helpers import HEADERS, post_text_draft, record_body


def _events(caplog: pytest.LogCaptureFixture, name: str) -> list[dict[str, Any]]:
    found = []
    for record in caplog.records:
        try:
            event = json.loads(record.getMessage())
        except ValueError:
            continue
        if event.get("event") == name:
            found.append(event)
    return found


def test_S08_task_reassignment_keeps_self_report(
    mock_client: TestClient, caplog: pytest.LogCaptureFixture
) -> None:
    """S-08：担当を変えたら、申告した「自分」がタスクに残り、操作記録にも出る（患者名は出さない）。"""
    body = {"assigned_to": "n04", "reported_by": "n02"}
    res = mock_client.patch("/api/tasks/t_demo1", json=body, headers=HEADERS)
    assert res.status_code == 200, res.text
    assert res.json()["task"]["assigned_reported_by"] == "n02"
    [event] = _events(caplog, "task_assignee_changed")
    assert (event["assigned_to"], event["reported_by"]) == ("n04", "n02")
    assert "中田" not in json.dumps(event, ensure_ascii=False)


def test_S08_patient_assignee_keeps_self_report(
    mock_client: TestClient, caplog: pytest.LogCaptureFixture
) -> None:
    """S-08：受け持ちを変えたら、申告した「自分」が名簿に残り、操作記録に出る。"""
    body = {"assigned_to": "n04", "reported_by": "n01"}
    patient = mock_client.patch("/api/patients/p305", json=body, headers=HEADERS).json()["patient"]
    assert patient["assigned_reported_by"] == "n01"
    [event] = _events(caplog, "patient_assignee_changed")
    assert (event["assigned_to"], event["reported_by"]) == ("n04", "n01")


def test_S08_confirm_keeps_self_report(mock_client: TestClient) -> None:
    """S-08：確定のときに送った「自分」が記録に残り、詳細で返る。"""
    draft = post_text_draft(mock_client, "p302")
    res = mock_client.post(
        "/api/records", json=record_body(draft, reported_by="n03"), headers=HEADERS
    )
    record_id = res.json()["record_id"]
    detail = mock_client.get(f"/api/records/{record_id}", headers=HEADERS).json()["record"]
    assert detail["confirmed_reported_by"] == "n03"


@pytest.mark.parametrize(
    ("method", "path", "body"),
    [
        ("PATCH", "/api/tasks/t_demo1", {"assigned_to": "n04", "reported_by": "n99"}),
        ("PATCH", "/api/patients/p305", {"assigned_to": "n04", "reported_by": "n99"}),
    ],
)
def test_S08_unknown_self_report_is_422(
    mock_client: TestClient, method: str, path: str, body: dict[str, str]
) -> None:
    """S-08：一覧にない「自分」は 422（unknown_nurse）で、何も変えない。"""
    res = mock_client.request(method, path, json=body, headers=HEADERS)
    assert (res.status_code, res.json()["error"]["code"]) == (422, "unknown_nurse")
    tasks = mock_client.get("/api/tasks", headers=HEADERS).json()["tasks"]
    assert all(t["assigned_to"] != "n04" for t in tasks)


def test_S08_unknown_self_report_on_confirm_is_422(mock_client: TestClient) -> None:
    """S-08：確定のときも、一覧にない「自分」は 422 で、記録を作らない。"""
    draft = post_text_draft(mock_client, "p302")
    res = mock_client.post(
        "/api/records", json=record_body(draft, reported_by="n99"), headers=HEADERS
    )
    assert res.status_code == 422
    assert mock_client.get("/api/records", headers=HEADERS).json()["records"] == []


def test_S08_without_self_report_stays_empty(mock_client: TestClient) -> None:
    """S-08：「自分」を送らない今の画面も動き、申告の欄は空（null）のまま。"""
    task = mock_client.patch(
        "/api/tasks/t_demo1", json={"assigned_to": "n04"}, headers=HEADERS
    ).json()["task"]
    assert (task["assigned_to"], task["assigned_reported_by"]) == ("n04", None)
    draft = post_text_draft(mock_client, "p302")
    res = mock_client.post("/api/records", json=record_body(draft), headers=HEADERS)
    detail = mock_client.get(f"/api/records/{res.json()['record_id']}", headers=HEADERS)
    assert detail.json()["record"]["confirmed_reported_by"] is None
