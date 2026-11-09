"""A-13：依頼のラベル（中身の種類 category・職種 role）。仕分けのためで、優先度ではない。"""

from typing import Any

import pytest
from fastapi.testclient import TestClient

from app.live.gemini_vertex import DRAFT_PROMPT
from app.main import create_app
from app.models.gemini import GeminiDraft
from app.models.labels import CATEGORIES, ROLES
from app.services.soap import to_soap
from tests.helpers import (
    HEADERS,
    gemini_draft_of,
    make_services,
    make_settings,
    post_text_draft,
    record_body,
)


@pytest.fixture
def app_and_store() -> tuple[TestClient, Any]:
    """保存先（メモリ）をのぞけるようにする。"""
    services = make_services()
    return TestClient(create_app(make_settings("mock"), services)), services.store


def _confirm_tasks(client: TestClient, store: Any, draft: dict[str, Any]) -> list[dict[str, Any]]:
    res = client.post("/api/records", json=record_body(draft), headers=HEADERS)
    assert res.status_code == 200, res.text
    return [store._tasks[t] for t in res.json()["tasks_created"]]  # テストでだけ中をのぞく


def test_A13_gemini_chooses_labels_from_the_single_list() -> None:
    """A-13：Gemini には一覧（定数1か所）から選ばせ、仕分けのためで優先度ではないと伝える。"""
    schema = GeminiDraft.model_json_schema()["$defs"]["GeminiRequest"]["properties"]
    assert tuple(schema["category"]["enum"]) == CATEGORIES
    assert tuple(schema["role"]["enum"]) == ROLES
    assert "仕分けのためで、優先度ではない" in DRAFT_PROMPT


def test_A13_missing_labels_from_gemini_become_other() -> None:
    """A-13：Gemini がラベルを返さなくても下書きは作れ、「その他」になる。"""
    draft = to_soap(gemini_draft_of("s1", lambda d: d["requests"][0].pop("category")))
    assert draft.requests[0].category == "その他"


def test_A13_A08_labels_do_not_change_urgency() -> None:
    """A-13・A-08：ラベルは緊急度に関係しない（緊急度は cue からコードが決める）。"""
    draft = to_soap(
        gemini_draft_of("s1", lambda d: d["requests"][0].update(category="痛みの訴え", role="医師"))
    )
    assert (draft.requests[0].category, draft.requests[0].urgency) == ("痛みの訴え", "none")


def test_A13_ai_labels_reach_tasks(app_and_store: tuple) -> None:
    """A-13：AI が付けたラベルは、下書きの依頼 → タスクに入り、set_by は ai。"""
    client, store = app_and_store
    draft = post_text_draft(client, "p305")  # 場面2：着替え・食事の依頼
    labels = [(r["category"], r["role"]) for r in draft["draft"]["requests"]]
    assert labels == [("着替え", "看護助手"), ("食事", "看護助手")]
    tasks = _confirm_tasks(client, store, draft)
    assert [(t["category"], t["role"]) for t in tasks] == labels
    assert {(t["category_set_by"], t["role_set_by"]) for t in tasks} == {("ai", "ai")}


def test_A13_nurse_changes_label_with_one_patch(mock_client: TestClient) -> None:
    """A-13：看護師が PATCH で変えたら、そのラベルの set_by だけ nurse になる。"""
    res = mock_client.patch("/api/tasks/t_demo4", json={"role": "看護師"}, headers=HEADERS)
    task = res.json()["task"]
    assert (task["role"], task["role_set_by"]) == ("看護師", "nurse")
    assert (task["category"], task["category_set_by"]) == ("物品", "ai")
    bad = mock_client.patch("/api/tasks/t_demo4", json={"category": "至急"}, headers=HEADERS)
    assert bad.status_code == 422  # 一覧にないラベル


@pytest.mark.parametrize(
    ("labels", "expected"),
    [({"category": "移動", "role": "看護師"}, ("移動", "看護師")), ({}, ("その他", "その他"))],
)
def test_A13_A12_nurse_request_uses_sent_labels(
    app_and_store: tuple, labels: dict[str, str], expected: tuple[str, str]
) -> None:
    """A-13・A-12：看護師が足した依頼は画面が送ったラベル（なければ「その他」）で、set_by は nurse。"""
    client, store = app_and_store
    draft = post_text_draft(client, "p302")
    draft["draft"]["requests"].append({"text": "車椅子で売店へ", "added_by": "nurse", **labels})
    task = _confirm_tasks(client, store, draft)[-1]
    assert (task["category"], task["role"]) == expected
    assert (task["category_set_by"], task["role_set_by"]) == ("nurse", "nurse")


def test_A13_create_task_with_and_without_labels(mock_client: TestClient) -> None:
    """A-13：POST /api/tasks もラベルを受ける（なければ「その他」）。看護師が作るので nurse。"""
    with_labels = {
        "patient_id": "p305",
        "text": "家族に電話",
        "category": "その他",
        "role": "看護師",
    }
    task = mock_client.post("/api/tasks", json=with_labels, headers=HEADERS).json()["task"]
    assert (task["role"], task["role_set_by"]) == ("看護師", "nurse")
    plain = mock_client.post(
        "/api/tasks", json={"patient_id": "p305", "text": "家族に電話"}, headers=HEADERS
    ).json()["task"]
    assert (plain["category"], plain["role"]) == ("その他", "その他")


def test_A13_old_clients_and_old_tasks_still_work(mock_client: TestClient) -> None:
    """A-13：ラベルを送らない今の画面も動き、見本タスクにはラベルが入っている。"""
    draft = post_text_draft(mock_client, "p302")
    for request in draft["draft"]["requests"]:
        request.pop("category"), request.pop("role")
    res = mock_client.post("/api/records", json=record_body(draft), headers=HEADERS)
    assert res.status_code == 200, res.text
    tasks = mock_client.get("/api/tasks", headers=HEADERS).json()["tasks"]
    demo = {t["id"]: (t["category"], t["role"]) for t in tasks if t["id"].startswith("t_demo")}
    assert demo["t_demo1"] == ("排泄", "看護師")
