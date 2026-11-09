"""総合テストのうち、依頼のラベル（中身の種類・職種、決まり A-13）の手順。お金はかからない。"""

from typing import Any

from app.models.labels import CATEGORIES, ROLES
from scripts.smoke_client import Smoke


def check_labels(smoke: Smoke, drafted: dict[str, Any], task_ids: list[str]) -> None:
    """下書きのラベルが一覧の中から選ばれ、タスクで1回の PATCH で変えられるかを確かめる。"""
    requests = drafted["draft"]["requests"]
    smoke.check(
        "ラベル：下書きの依頼のラベルが一覧の中から選ばれている",
        all(r["category"] in CATEGORIES and r["role"] in ROLES for r in requests),
        str([(r["category"], r["role"]) for r in requests]),
    )
    if not task_ids:
        return
    res = smoke.request("PATCH", f"/api/tasks/{task_ids[0]}", json={"role": "看護助手"})
    if smoke.expect_status("ラベル：職種を変えて 200", res, 200):
        task = res.json()["task"]
        smoke.check(
            "ラベル：変えた職種が入り、role_set_by が nurse",
            task["role"] == "看護助手" and task["role_set_by"] == "nurse",
        )
