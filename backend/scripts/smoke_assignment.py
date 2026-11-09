"""総合テストのうち、タスクの担当の割り振り（決まり S-08）の手順。お金はかからない。"""

from typing import Any

from scripts.smoke_client import Smoke


def _nurse_ids(smoke: Smoke) -> list[str]:
    res = smoke.request("GET", "/api/nurses")
    if not smoke.expect_status("担当：看護師の一覧で 200", res, 200):
        return []
    ids = [n["id"] for n in res.json()["nurses"]]
    smoke.check("担当：看護師が2人以上いる", len(ids) >= 2, f"{len(ids)}人")
    return ids


def check_assignment(smoke: Smoke, drafted: dict[str, Any], task_ids: list[str]) -> None:
    """確定で作ったタスクが受け持ちの担当になり、担当に回せて、担当で絞れるかを確かめる。"""
    nurse_ids = _nurse_ids(smoke)
    expected = drafted["patient"]["assigned_to"]
    res = smoke.request("GET", "/api/tasks", params={"status": "all"})
    if not nurse_ids or not smoke.expect_status("担当：タスクの一覧で 200", res, 200):
        return
    mine = [t for t in res.json()["tasks"] if t["id"] in task_ids]
    smoke.check(
        "担当：確定で作ったタスクは患者の受け持ちが担当（rule）",
        bool(mine)
        and all((t["assigned_to"], t["assigned_set_by"]) == (expected, "rule") for t in mine),
        f"受け持ち={expected}",
    )
    other = next((n for n in nurse_ids if n != expected), nurse_ids[0])
    body = {"assigned_to": other, "reported_by": expected or other}
    res = smoke.request("PATCH", f"/api/tasks/{task_ids[0]}", json=body)
    if smoke.expect_status("担当：担当に回して 200", res, 200):
        task = res.json()["task"]
        smoke.check(
            "担当：回した先が担当になり、assigned_set_by が nurse",
            (task["assigned_to"], task["assigned_set_by"]) == (other, "nurse"),
        )
        smoke.check(
            "担当：回した人の自己申告が残る",
            task["assigned_reported_by"] == body["reported_by"],
        )
    res = smoke.request("GET", "/api/tasks", params={"status": "all", "assigned_to": other})
    if smoke.expect_status("担当：担当で絞って 200", res, 200):
        listed = res.json()["tasks"]
        smoke.check(
            "担当：絞った一覧に回したタスクが入り、ほかの担当は入らない",
            task_ids[0] in {t["id"] for t in listed}
            and all(t["assigned_to"] == other for t in listed),
        )
    res = smoke.request("PATCH", f"/api/tasks/{task_ids[0]}", json={"assigned_to": "n_unknown"})
    smoke.expect_status("担当：一覧にない看護師は 422", res, 422)
    check_assignee_change(smoke, drafted, nurse_ids)


def check_assignee_change(smoke: Smoke, drafted: dict[str, Any], nurse_ids: list[str]) -> None:
    """患者の受け持ちを変えると名簿に出て、rule のタスクが移るかを確かめ、元に戻す。

    live では Firestore の名簿を書き換えるので、最後に必ず元の受け持ちに戻す。
    """
    patient_id, original = drafted["patient"]["id"], drafted["patient"]["assigned_to"]
    other = next((n for n in nurse_ids if n != original), None)
    if other is None or original is None:
        smoke.skip("受け持ち：変える", "看護師か受け持ちがない")
        return
    res = smoke.request("PATCH", f"/api/patients/{patient_id}", json={"assigned_to": other})
    if smoke.expect_status("受け持ち：変えて 200", res, 200):
        smoke.check("受け持ち：新しい受け持ちが返る", res.json()["patient"]["assigned_to"] == other)
        listed = smoke.request("GET", "/api/patients")
        if smoke.expect_status("受け持ち：名簿で 200", listed, 200):
            mine = [p for p in listed.json()["patients"] if p["id"] == patient_id]
            smoke.check("受け持ち：名簿に変えた受け持ちが出る", mine[0]["assigned_to"] == other)
    res = smoke.request("PATCH", f"/api/patients/{patient_id}", json={"assigned_to": original})
    smoke.expect_status("受け持ち：元に戻して 200", res, 200)
