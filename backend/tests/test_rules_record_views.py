"""保存した記録を見る API（GET /api/records・/api/records/{id}）。P-02・P-03 の範囲で返す。"""

from datetime import timedelta
from typing import Any

import pytest
from fastapi.testclient import TestClient

from app.main import create_app
from app.routes.record_views import MAX_RECORDS
from app.services.clock import now_jst
from app.store.firestore_store import FirestoreStore
from tests.helpers import HEADERS, make_services, make_settings, post_text_draft, record_body
from tests.test_live_clients import FakeFirestore


@pytest.fixture
def app_and_records() -> tuple[TestClient, dict[str, Any]]:
    """確定した記録をのぞけるように、保存先（メモリ）の中身も返す。"""
    services = make_services()
    client = TestClient(create_app(make_settings("mock"), services))
    return client, services.store._records  # テストでだけ中をのぞく


def _confirm(client: TestClient, patient_id: str) -> tuple[dict[str, Any], dict[str, Any]]:
    draft = post_text_draft(client, patient_id)
    confirmed_ok = patient_id == "p302"  # p302 だけ患者の照合が緑
    body = record_body(draft, patient_confirmed=not confirmed_ok)
    decisions = [
        {"path": c["path"], "action": "keep"} for c in draft["checks"] if c["level"] == "stop"
    ]
    res = client.post("/api/records", json={**body, "decisions": decisions}, headers=HEADERS)
    assert res.status_code == 200, res.text
    return draft, res.json()


def test_P02_record_detail_returns_only_evidence_utterances(app_and_records: tuple) -> None:
    """P-02：詳細は記録の全体とカルテ用の文。会話は根拠になった発言だけで、全文は返さない。"""
    client, _ = app_and_records
    draft, confirmed = _confirm(client, "p302")
    res = client.get(f"/api/records/{confirmed['record_id']}", headers=HEADERS)
    assert res.status_code == 200, res.text
    record = res.json()["record"]
    assert record["chart_text"] == confirmed["chart_text"]  # 保存した記録から作り直しても同じ
    assert record["soap"] == draft["draft"]["soap"]
    assert "utterances" not in record
    saved_ids = [u["id"] for u in record["evidence_utterances"]]
    assert 0 < len(saved_ids) < len(draft["utterances"])
    assert record["patient_check"]["level"] == "ok"


@pytest.mark.parametrize("use_firestore", [False, True], ids=["memory", "firestore"])
def test_A01_saved_requests_reference_their_created_tasks(use_firestore: bool) -> None:
    """確定した依頼とタスクは、保存した行の順が変わっても対応する。"""
    services = make_services()
    db = FakeFirestore() if use_firestore else None
    if db is not None:
        services.store = FirestoreStore(db)
        services.store.seed_patients(services.roster)
    client = TestClient(create_app(make_settings("mock"), services))
    _, confirmed = _confirm(client, "p305")
    record_id = confirmed["record_id"]
    task_ids = confirmed["tasks_created"]
    assert len(task_ids) == 2

    saved = db.data["records", record_id] if db is not None else services.store._records[record_id]
    assert [request["task_id"] for request in saved["requests"]] == task_ids
    tasks = client.get("/api/tasks", params={"status": "all"}, headers=HEADERS).json()["tasks"]
    linked = {t["id"]: t["text"] for t in tasks if t["record_id"] == record_id}
    assert linked == {r["task_id"]: r["text"] for r in saved["requests"]}

    saved["requests"].reverse()
    detail = client.get(f"/api/records/{record_id}", headers=HEADERS)
    assert detail.status_code == 200
    assert [r["task_id"] for r in detail.json()["record"]["requests"]] == task_ids[::-1]


def test_A01_older_record_without_task_link_is_readable(app_and_records: tuple) -> None:
    """ひも付けを保存する前の記録も閲覧できる。"""
    client, records = app_and_records
    _, confirmed = _confirm(client, "p302")
    record_id = confirmed["record_id"]
    for request in records[record_id]["requests"]:
        request.pop("task_id", None)

    detail = client.get(f"/api/records/{record_id}", headers=HEADERS)
    assert detail.status_code == 200
    assert [r["task_id"] for r in detail.json()["record"]["requests"]] == [None]
    task_id = confirmed["tasks_created"][0]
    patch = client.patch(f"/api/tasks/{task_id}", json={"category": "食事"}, headers=HEADERS)
    assert patch.status_code == 200
    assert client.get(f"/api/records/{record_id}", headers=HEADERS).json() == detail.json()


@pytest.mark.parametrize("use_firestore", [False, True], ids=["memory", "firestore"])
def test_A08_A13_task_changes_reach_the_matching_request_only(use_firestore: bool) -> None:
    """緊急度とラベルは、順番が変わっても正しい記録の依頼にだけ反映する。"""
    services = make_services()
    db = FakeFirestore() if use_firestore else None
    if db is not None:
        services.store = FirestoreStore(db)
        services.store.seed_patients(services.roster)
    client = TestClient(create_app(make_settings("mock"), services))
    _, confirmed = _confirm(client, "p305")
    _, another = _confirm(client, "p305")
    record_id = confirmed["record_id"]
    task_id = confirmed["tasks_created"][0]
    saved = db.data["records", record_id] if db is not None else services.store._records[record_id]
    saved["requests"].reverse()
    record_url = f"/api/records/{record_id}"
    other_url = f"/api/records/{another['record_id']}"
    before = client.get(record_url, headers=HEADERS).json()["record"]
    other_before = client.get(other_url, headers=HEADERS).json()
    assert before["requests"][1]["task_id"] == task_id

    changes = {"urgency": "said_urgent", "category": "清潔", "role": "看護師"}
    patch = client.patch(
        f"/api/tasks/{task_id}", json={**changes, "status": "done"}, headers=HEADERS
    )
    assert patch.status_code == 200, patch.text
    assert patch.json()["task"]["status"] == "done"
    assert {key: patch.json()["task"][key] for key in changes} == changes
    expected_requests = [before["requests"][0], {**before["requests"][1], **changes}]
    assert client.get(record_url, headers=HEADERS).json()["record"] == {
        **before,
        "revision": before["revision"] + 1,
        "requests": expected_requests,
    }
    assert client.get(other_url, headers=HEADERS).json() == other_before


def test_A08_firestore_commit_failure_leaves_task_and_record_unchanged() -> None:
    """Firestore の保存が失敗したとき、記録かタスクの片方だけが残らない。"""
    services = make_services()
    db = FakeFirestore()
    services.store = FirestoreStore(db)
    services.store.seed_patients(services.roster)
    client = TestClient(create_app(make_settings("mock"), services), raise_server_exceptions=False)
    _, confirmed = _confirm(client, "p302")
    record_id = confirmed["record_id"]
    task_id = confirmed["tasks_created"][0]
    record_key, task_key = ("records", record_id), ("tasks", task_id)
    record_before, task_before = dict(db.data[record_key]), dict(db.data[task_key])
    db.fail_transaction = True

    patch = client.patch(f"/api/tasks/{task_id}", json={"urgency": "said_urgent"}, headers=HEADERS)
    assert patch.status_code == 500
    assert db.data[record_key] == record_before
    assert db.data[task_key] == task_before


def test_P02_record_list_is_short_summaries_newest_first(app_and_records: tuple) -> None:
    """一覧は新しい順の短い要約。patient_id で絞れる。"""
    client, records = app_and_records
    _, first = _confirm(client, "p302")
    _, second = _confirm(client, "p308")
    records[first["record_id"]]["created_at"] -= timedelta(minutes=5)  # 先に確定したことにする
    listed = client.get("/api/records", headers=HEADERS).json()["records"]
    assert [r["record_id"] for r in listed] == [second["record_id"], first["record_id"]]
    assert set(listed[0]) == {
        "record_id", "patient_id", "room", "name", "full_name", "created_at",
        "s_preview", "o_preview", "request_count",
    }  # fmt: skip
    only = client.get("/api/records", params={"patient_id": "p302"}, headers=HEADERS).json()
    assert [r["record_id"] for r in only["records"]] == [first["record_id"]]


def test_P03_expired_records_are_not_returned(app_and_records: tuple) -> None:
    """P-03：期限（翌日0時）を過ぎた記録は、TTL で消える前でも一覧・詳細に出さない。"""
    client, records = app_and_records
    _, confirmed = _confirm(client, "p302")
    records[confirmed["record_id"]]["expires_at"] = now_jst() - timedelta(seconds=1)
    assert client.get("/api/records", headers=HEADERS).json()["records"] == []
    res = client.get(f"/api/records/{confirmed['record_id']}", headers=HEADERS)
    assert res.status_code == 404 and res.json()["error"]["code"] == "record_not_found"


def test_SEC04_record_list_is_capped(app_and_records: tuple) -> None:
    """SEC-04：一覧は100件まで（新しいものから）。"""
    client, records = app_and_records
    _, confirmed = _confirm(client, "p302")
    base = records[confirmed["record_id"]]
    for i in range(MAX_RECORDS + 5):
        records[f"r_p302_bulk{i}"] = {
            **base,
            "created_at": base["created_at"] + timedelta(seconds=i),
        }
    listed = client.get("/api/records", headers=HEADERS).json()["records"]
    assert len(listed) == MAX_RECORDS and listed[0]["record_id"] == f"r_p302_bulk{MAX_RECORDS + 4}"


@pytest.mark.parametrize(
    ("url", "status"),
    [
        ("/api/records/r_p302_nothing", 404),
        ("/api/records/x..y", 422),  # 記録の id の形でない
        ("/api/records?patient_id=../p302", 422),
    ],
)
def test_SEC04_record_ids_are_validated(mock_client: TestClient, url: str, status: int) -> None:
    """SEC-04：記録の id と patient_id は形を確かめる。"""
    assert mock_client.get(url, headers=HEADERS).status_code == status


def test_SEC01_record_views_need_passcode(mock_client: TestClient) -> None:
    """SEC-01：記録を見るにも合言葉が要る。"""
    assert mock_client.get("/api/records").status_code == 401
    assert mock_client.get("/api/records/r_p302_x").status_code == 401


def test_P03_firestore_record_reads_skip_expired() -> None:
    """P-03：Firestore からの読み出しも、期限切れを除き、patient_id で絞れる。"""
    store, now = FirestoreStore(FakeFirestore()), now_jst()
    live = {"patient_id": "p302", "expires_at": now + timedelta(hours=1)}
    store.save_record("r_p302_a", live, [])
    store.save_record("r_p305_b", {**live, "patient_id": "p305"}, [])
    store.save_record("r_p302_old", {**live, "expires_at": now - timedelta(seconds=1)}, [])
    assert [r["id"] for r in store.list_records("p302", now)] == ["r_p302_a"]
    assert {r["id"] for r in store.list_records(None, now)} == {"r_p302_a", "r_p305_b"}
    assert store.get_record("r_p302_a", now)["id"] == "r_p302_a"  # type: ignore[index]
    assert store.get_record("r_p302_old", now) is None
