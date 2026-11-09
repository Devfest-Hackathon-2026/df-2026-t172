"""MODE=mock で、全 API が data-model.md どおりに応答するか。"""

from typing import Any

from fastapi.testclient import TestClient

from tests.helpers import HEADERS, record_body


def _draft(client: TestClient, patient_id: str) -> dict[str, Any]:
    body = {"patient_id": patient_id, "transcript": "看護師: こんにちは"}
    res = client.post("/api/drafts", json=body, headers=HEADERS)
    assert res.status_code == 200, res.text
    return res.json()


_record_body = record_body


def test_SEC01_passcode_is_required(mock_client: TestClient) -> None:
    res = mock_client.get("/api/patients")
    assert res.status_code == 401
    assert res.json() == {
        "mode": "mock",
        "error": {"code": "bad_passcode", "message": "合言葉が違います"},
    }
    assert mock_client.get("/api/patients", headers={"X-Passcode": "wrong"}).status_code == 401


def test_health_needs_no_passcode(mock_client: TestClient) -> None:
    """/healthz は Cloud Run が予約しているので /api/health に置く。"""
    assert mock_client.get("/api/health").json() == {"mode": "mock", "status": "ok"}


def test_patients(mock_client: TestClient) -> None:
    body = mock_client.get("/api/patients", headers=HEADERS).json()
    assert body["mode"] == "mock"
    assert body["patients"][0] == {
        "id": "p302", "room": "302", "bed": "A", "name": "田中", "kana": "たなか", "full_name": "田中 一郎", "full_kana": "たなか いちろう", "ward": "東3病棟", "assigned_to": "n01", "assigned_reported_by": None,
    }  # fmt: skip


def test_text_draft_returns_scenario_by_patient(mock_client: TestClient) -> None:
    body = _draft(mock_client, "p305")
    assert body["input"] == "text"
    assert body["patient"]["id"] == "p305"
    assert [r["urgency"] for r in body["draft"]["requests"]] == ["none", "timed"]
    assert body["draft"]["soap"]["A"] == "" and body["draft"]["soap"]["P"] == ""


def test_audio_draft_multipart(mock_client: TestClient) -> None:
    res = mock_client.post(
        "/api/drafts",
        data={"patient_id": "p312", "consent_confirmed": "true"},
        files={"audio": ("rec.webm", b"fake-audio", "audio/webm")},
        headers=HEADERS,
    )
    body = res.json()
    assert res.status_code == 200 and body["input"] == "audio"
    assert body["checks"][0]["code"] == "multiple_values"
    assert body["utterances"][0]["start"] == 0.0


def test_other_patient_gets_scene1_with_recomputed_match(mock_client: TestClient) -> None:
    body = _draft(mock_client, "p303")  # 隣の行（中田さん）を選んだ
    assert body["patient"]["name"] == "中田"
    assert body["patient_match"]["level"] == "stop"


def test_unknown_patient_is_404(mock_client: TestClient) -> None:
    body = {"patient_id": "p999", "transcript": "x"}
    res = mock_client.post("/api/drafts", json=body, headers=HEADERS)
    assert res.status_code == 404 and res.json()["error"]["code"] == "patient_not_found"


def test_verify_code_only_and_mock_entail(mock_client: TestClient) -> None:
    draft = _draft(mock_client, "p302")
    draft["draft"]["soap"]["S"][0]["text"] = "現在の痛みは7/10。"
    body = {"utterances": draft["utterances"], "draft": draft["draft"], "entail": False}
    res = mock_client.post("/api/verify", json=body, headers=HEADERS).json()
    assert res["mode"] == "mock" and res["missing"] == ["呼吸数", "SpO2"]
    assert [c["code"] for c in res["checks"]] == ["number_not_in_evidence"]

    res = mock_client.post("/api/verify", json={**body, "entail": True}, headers=HEADERS).json()
    assert {c["code"] for c in res["checks"]} == {"number_not_in_evidence", "entail_unclear"}


def test_record_confirm_and_tasks(mock_client: TestClient) -> None:
    draft = _draft(mock_client, "p305")
    res = mock_client.post("/api/records", json=_record_body(draft), headers=HEADERS)
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["chart_text"].startswith("【305号室A 佐藤 和夫様】")
    assert "BS 182" in body["chart_text"]
    assert len(body["tasks_created"]) == 2

    tasks = mock_client.get("/api/tasks", headers=HEADERS).json()["tasks"]
    urgencies = [t["urgency"] for t in tasks]
    assert urgencies == sorted(urgencies, key=["said_urgent", "timed", "none"].index)
    created = [t for t in tasks if t["id"] in body["tasks_created"]]
    assert {t["record_id"] for t in created} == {body["record_id"]}


def test_A05_record_blocked_until_stop_checks_decided(mock_client: TestClient) -> None:
    draft = _draft(mock_client, "p308")  # 場面3：「脱水傾向あり」が二段目で止まる
    res = mock_client.post("/api/records", json=_record_body(draft), headers=HEADERS)
    assert res.status_code == 409 and res.json()["error"]["code"] == "undecided_checks"

    decisions = [{"path": "soap.S[2]", "action": "delete"}]
    res = mock_client.post(
        "/api/records", json=_record_body(draft, decisions=decisions), headers=HEADERS
    )
    assert res.status_code == 200
    assert "脱水" not in res.json()["chart_text"]


def test_record_cannot_drop_code_checks_by_omitting_them(mock_client: TestClient) -> None:
    draft = _draft(mock_client, "p302")
    draft["draft"]["vitals"][0]["value"] = "37.9"  # 画面から checks を送らなくても止まる
    res = mock_client.post("/api/records", json=_record_body(draft, checks=[]), headers=HEADERS)
    assert res.status_code == 409


def test_record_needs_patient_confirmation(mock_client: TestClient) -> None:
    draft = _draft(mock_client, "p310")  # 場面4：名前を言っていない → confirm
    res = mock_client.post("/api/records", json=_record_body(draft), headers=HEADERS)
    assert res.status_code == 409 and res.json()["error"]["code"] == "patient_not_confirmed"
    body = _record_body(draft, patient_confirmed=True)
    assert mock_client.post("/api/records", json=body, headers=HEADERS).status_code == 200


def test_record_invalid_decision_path(mock_client: TestClient) -> None:
    draft = _draft(mock_client, "p302")
    decisions = [{"path": "soap.S[9]", "action": "delete"}]
    res = mock_client.post(
        "/api/records", json=_record_body(draft, decisions=decisions), headers=HEADERS
    )
    assert res.status_code == 422 and res.json()["error"]["code"] == "invalid_decision"


def test_patch_task(mock_client: TestClient) -> None:
    res = mock_client.patch("/api/tasks/t_demo3", json={"urgency": "said_urgent"}, headers=HEADERS)
    assert res.json()["task"]["urgency_set_by"] == "nurse"
    res = mock_client.patch("/api/tasks/t_demo3", json={"status": "done"}, headers=HEADERS)
    assert res.json()["task"]["done_at"] is not None
    open_ids = [t["id"] for t in mock_client.get("/api/tasks", headers=HEADERS).json()["tasks"]]
    assert "t_demo3" not in open_ids
    done = mock_client.get("/api/tasks?status=done", headers=HEADERS).json()["tasks"]
    assert [t["id"] for t in done] == ["t_demo3"]
    assert (
        mock_client.patch("/api/tasks/nope", json={"status": "done"}, headers=HEADERS).status_code
        == 404
    )


def test_validation_error_format(mock_client: TestClient) -> None:
    res = mock_client.post("/api/verify", json={"draft": {}}, headers=HEADERS)
    assert res.status_code == 422
    assert res.json()["error"]["code"] == "invalid_request"
