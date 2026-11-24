"""保存済み記録の手動訂正と、対応するタスクの一括更新。"""

from datetime import timedelta

import pytest
from fastapi.testclient import TestClient

from app.main import create_app
from app.services.clock import now_jst
from app.store.firestore_store import FirestoreStore
from tests.helpers import HEADERS, make_services, make_settings, post_text_draft, record_body
from tests.test_live_clients import FakeFirestore


@pytest.fixture(params=["memory", "firestore"])
def amendment(request: pytest.FixtureRequest):
    """両方の保存先で同じ API を確認する。外部サービスは差し替える。"""
    services = make_services()
    db = FakeFirestore() if request.param == "firestore" else None
    if db is not None:
        services.store = FirestoreStore(db)
        services.store.seed_patients(services.roster)
    client = TestClient(create_app(make_settings("mock"), services))
    draft = post_text_draft(client, "p305")
    body = record_body(draft, patient_confirmed=True)
    body["decisions"] = [
        {"path": check["path"], "action": "keep"}
        for check in draft["checks"]
        if check["level"] == "stop"
    ]
    confirmed = client.post("/api/records", json=body, headers=HEADERS).json()
    record_id = confirmed["record_id"]
    url = f"/api/records/{record_id}"
    record = client.get(url, headers=HEADERS).json()["record"]
    raw = db.data["records", record_id] if db is not None else services.store._records[record_id]
    return client, url, record, raw, body, db


def test_A12_R03_P02_manual_edit_is_independent_of_original_utterance(amendment: tuple) -> None:
    client, url, before, _, _, _ = amendment
    assert (
        client.patch(url, json={"revision": 0, "changes": {"soap": {"A": "追記"}}}).status_code
        == 401
    )
    plans = before["care_plans"]
    res = client.patch(
        url,
        headers=HEADERS,
        json={
            "revision": 0,
            "changes": {
                "vitals": [{"item": "血糖", "value": "92"}],
                "soap": {
                    "S": [
                        {
                            "index": 0,
                            "text": "後でメールで受け取った内容",
                            "plan_id": plans[0]["id"] if plans else None,
                        }
                    ],
                    "A": "追記",
                    "P": "次回の確認",
                },
                "manual_needed": [{"text": "口頭で受け取った内容"}],
                "doctor_questions": [{"text": "質問の追記"}],
            },
        },
    )
    assert res.status_code == 200, res.text
    saved = res.json()["record"]
    assert saved["record_id"] == before["record_id"]
    assert saved["created_at"] == before["created_at"]
    assert saved["revision"] == 1
    assert "後でメールで受け取った内容" in saved["chart_text"]
    assert saved["soap"]["S"][0]["evidence"] == []
    assert saved["soap"]["S"][0]["added_by"] == "nurse"
    assert saved["soap"]["O"] == before["soap"]["O"]
    assert saved["vitals"][0]["source"] == "manual"
    assert {"soap.S[0]", "soap.A", "soap.P", "vitals[0]"} <= set(saved["amended_paths"])
    assert all(check["path"] != "soap.S[0]" for check in saved["kept_after_check"])
    assert client.get(url, headers=HEADERS).json() == res.json()


def test_A08_A13_S08_R02_request_edit_keeps_task_status_and_assignee(amendment: tuple) -> None:
    client, url, before, _, original_body, _ = amendment
    first, second = [item["task_id"] for item in before["requests"]]
    done = client.patch(
        f"/api/tasks/{second}", headers=HEADERS, json={"status": "done", "assigned_to": "n01"}
    )
    assert done.status_code == 200, done.text
    res = client.patch(
        url,
        headers=HEADERS,
        json={
            "revision": 0,
            "changes": {
                "requests": [
                    {
                        "task_id": second,
                        "text": "本人から別の会話で頼まれた付き添い",
                        "urgency": "timed",
                        "category": "付き添い",
                        "role": "看護助手",
                    },
                    {
                        "text": "口頭で受けた依頼",
                        "urgency": "none",
                        "category": "その他",
                        "role": "その他",
                    },
                ]
            },
        },
    )
    assert res.status_code == 200, res.text
    updated = res.json()["record"]
    new_id = updated["requests"][1]["task_id"]
    tasks = client.get("/api/tasks?status=all", headers=HEADERS).json()["tasks"]
    by_id = {task["id"]: task for task in tasks}
    assert first not in by_id
    assert by_id[second]["status"] == "done"
    assert by_id[second]["assigned_to"] == "n01"
    assert by_id[second]["patient_words"] == []
    assert by_id[second]["cue"] is None
    assert by_id[second]["urgency_set_by"] == "nurse"
    assert by_id[new_id]["status"] == "open"
    assert by_id[new_id]["text"] == "口頭で受けた依頼"
    replay = client.post("/api/records", headers=HEADERS, json=original_body)
    assert replay.status_code == 200
    assert client.get(url, headers=HEADERS).json()["record"] == updated
    assert replay.json()["tasks_created"] == [second, new_id]


def test_R03_P03_reject_wrong_plan_stale_version_and_expired_record(amendment: tuple) -> None:
    client, url, record, raw, _, _ = amendment
    assert (
        client.patch(
            url,
            headers=HEADERS,
            json={
                "revision": 0,
                "changes": {
                    "soap": {"S": [{"index": 0, "text": "記録", "plan_id": "other_patient_plan"}]}
                },
            },
        ).json()["error"]["code"]
        == "unknown_care_plan"
    )
    changed = client.patch(
        f"/api/tasks/{record['requests'][0]['task_id']}", headers=HEADERS, json={"category": "清潔"}
    )
    assert changed.status_code == 200
    assert (
        client.patch(
            url,
            headers=HEADERS,
            json={"revision": 0, "changes": {"soap": {"A": "先に変更された記録"}}},
        ).status_code
        == 409
    )
    assert (
        client.patch(
            url,
            headers=HEADERS,
            json={
                "revision": 1,
                "changes": {"requests": [{"task_id": "t_another", "text": "別のタスク"}]},
            },
        ).status_code
        == 422
    )
    raw["expires_at"] = now_jst() - timedelta(seconds=1)
    assert (
        client.patch(
            url, headers=HEADERS, json={"revision": 1, "changes": {"soap": {"A": "期限切れの記録"}}}
        ).status_code
        == 404
    )


def test_A06_P02_reordering_preserves_evidence_for_retained_items(amendment: tuple) -> None:
    """並び替え後も、元の文にだけ根拠と「残す」の印を出す。"""
    client, url, _, raw, _, _ = amendment
    original = raw["soap"]["S"][0]
    evidence = original["evidence"][0]
    raw["kept_after_check"] = [{"path": "soap.S[0]", "codes": ["entail_unclear"], "note": "確認"}]
    raw["soap"]["S"].append({**original, "text": "すでに訂正した文", "evidence": []})
    raw["amended_paths"] = ["soap.S[1]"]
    rows = [{"index": 1, "text": "すでに訂正した文"}, {"index": 0, "text": original["text"]}]
    result = client.patch(
        url, headers=HEADERS, json={"revision": 0, "changes": {"soap": {"S": rows}}}
    ).json()["record"]
    assert result["amended_paths"] == ["soap.S[0]"]
    assert result["kept_after_check"][0]["path"] == "soap.S[1]"
    assert evidence in result["soap"]["S"][1]["evidence"]
    assert result["soap"]["S"][0]["evidence"] == []

    rows = [{"index": 1, "text": "別の情報で訂正した文"}]
    result = client.patch(
        url, headers=HEADERS, json={"revision": 1, "changes": {"soap": {"S": rows}}}
    ).json()["record"]
    assert result["kept_after_check"] == []
    assert result["amended_paths"] == ["soap.S[0]"]
    assert result["soap"]["S"][0]["evidence"] == []
    assert evidence not in {u["id"] for u in result["evidence_utterances"]}


def test_R02_P02_legacy_requests_and_injected_evidence_are_rejected(amendment: tuple) -> None:
    """ひも付けのない旧記録でも、依頼以外は手動で直せる。"""
    client, url, _, raw, _, _ = amendment
    for row in raw["requests"]:
        del row["task_id"]
    res = client.patch(
        url,
        headers=HEADERS,
        json={"revision": 0, "changes": {"requests": [], "soap": {"A": "訂正"}}},
    )
    assert res.status_code == 422
    assert res.json()["error"]["code"] == "unlinked_requests"
    assert raw.get("revision", 0) == 0
    res = client.patch(
        url,
        headers=HEADERS,
        json={"revision": 0, "changes": {"soap": {"S": [{"text": "手入力", "evidence": ["u1"]}]}}},
    )
    assert res.status_code == 422
    res = client.patch(
        url, headers=HEADERS, json={"revision": 0, "changes": {"soap": {"A": "訂正"}}}
    )
    assert res.status_code == 200
    assert res.json()["record"]["soap"]["A"] == "訂正"
    assert len(res.json()["record"]["requests"]) == len(raw["requests"])


def test_A01_R02_record_and_tasks_are_unchanged_on_write_failure(amendment: tuple) -> None:
    """片方だけに変更が残らないことを両方の保存先で確認する。"""
    client, url, record, _, _, db = amendment
    first, second = [row["task_id"] for row in record["requests"]]
    changes = {"soap": {"P": "追記"}, "requests": [{"task_id": first, "text": "訂正"}]}
    if db is not None:
        db.fail_transaction = True
        res = client.patch(url, headers=HEADERS, json={"revision": 0, "changes": changes})
        assert res.status_code == 500
        db.fail_transaction = False
    else:
        # 対応するタスクが欠けている場合も、変更を始める前に止める。
        del client.app.state.services.store._tasks[second]
        res = client.patch(url, headers=HEADERS, json={"revision": 0, "changes": changes})
        assert res.status_code == 422
    assert client.get(url, headers=HEADERS).json()["record"] == record
    tasks = client.get("/api/tasks?status=all", headers=HEADERS).json()["tasks"]
    assert (
        next(task for task in tasks if task["id"] == first)["text"] == record["requests"][0]["text"]
    )
    if db is not None:
        assert any(task["id"] == second for task in tasks)
