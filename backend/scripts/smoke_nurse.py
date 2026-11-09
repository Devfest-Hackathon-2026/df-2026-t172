"""総合テストのうち、看護師が足す要素とタスクを直接作る手順（決まり A-12）。

どちらも Gemini を呼ばない（看護師が足した要素は二段目にかけないため、お金はかからない）。
"""

from typing import Any

from scripts.smoke_client import Smoke

NURSE_REQUEST_TEXT = "（総合テスト）看護師が足した依頼"


def nurse_request(drafted: dict[str, Any]) -> dict[str, Any]:
    """確定のときに足す、看護師の依頼。根拠には最初の患者の発言を選ぶ。"""
    patient_ids = [u["id"] for u in drafted["utterances"] if u["speaker"] == "patient"]
    return {
        "text": NURSE_REQUEST_TEXT,
        "urgency": "timed",
        "cue": {"kind": "時間指定", "text": "15時", "evidence": []},
        "evidence": patient_ids[:1],
        "added_by": "nurse",
    }


def check_nurse_task(smoke: Smoke, task_ids: list[str]) -> None:
    """看護師が足した依頼が、看護師の決めた緊急度でタスクになったかを確かめる。"""
    res = smoke.request("GET", "/api/tasks", params={"status": "all"})
    if not smoke.expect_status("看護師の依頼：タスクの一覧で 200", res, 200):
        return
    mine = [t for t in res.json()["tasks"] if t["id"] in task_ids]
    added = [t for t in mine if t["text"] == NURSE_REQUEST_TEXT]
    smoke.check(
        "看護師の依頼：タスクになり、urgency_set_by が nurse",
        len(added) == 1 and added[0]["urgency_set_by"] == "nurse",
    )


def create_task_directly(smoke: Smoke, patient_id: str) -> None:
    """POST /api/tasks でタスクを直接作り、記録なしで一覧に出るかを確かめる。"""
    body = {"patient_id": patient_id, "text": "（総合テスト）直接作ったタスク", "urgency": "none"}
    res = smoke.request("POST", "/api/tasks", json=body)
    if not smoke.expect_status("タスクを直接作る：200", res, 200):
        return
    task = res.json()["task"]
    smoke.check(
        "タスクを直接作る：record_id が null・urgency_set_by が nurse",
        task["record_id"] is None and task["urgency_set_by"] == "nurse",
    )
    res = smoke.request("GET", "/api/tasks", params={"status": "open"})
    if smoke.expect_status("タスクを直接作る：一覧で 200", res, 200):
        listed = {t["id"] for t in res.json()["tasks"]}
        smoke.check("タスクを直接作る：一覧に出る", task["id"] in listed)
