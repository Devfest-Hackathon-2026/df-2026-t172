"""総合テストのうち、下書き → 照合 → 確定 → タスクの流れ（画面が呼ぶ順）。

live では `/api/drafts` と `/api/verify`（entail=true）が Gemini を呼ぶ（お金がかかる）。
呼んでよいかは `scripts.smoke_test` が決めてから、ここを呼ぶ。
"""

import json
import re
import time
from copy import deepcopy
from pathlib import Path
from typing import Any

from scripts.smoke_assignment import check_assignment
from scripts.smoke_client import Smoke
from scripts.smoke_labels import check_labels
from scripts.smoke_nurse import check_nurse_task, create_task_directly, nurse_request

SCENARIOS = Path(__file__).resolve().parents[1] / "mock" / "source" / "scenarios.json"
SPEAKER_PREFIX = {"nurse": "看護師", "patient": "患者"}


def scene1() -> tuple[str, str]:
    """場面1（302号室 田中さんの検温）の患者の id と、テキスト入力の形の会話。"""
    scenario = json.loads(SCENARIOS.read_text(encoding="utf-8"))["scenarios"][0]
    lines = [f"{SPEAKER_PREFIX.get(u['speaker'], '')}: {u['text']}" for u in scenario["utterances"]]
    return scenario["patient_id"], "\n".join(lines)


def create_draft(smoke: Smoke) -> dict[str, Any] | None:
    """テキストで下書きを作る。形と中身（患者・バイタル・抜け・依頼）を確かめる。"""
    patient_id, transcript = scene1()
    res = smoke.request(
        "POST", "/api/drafts", json={"patient_id": patient_id, "transcript": transcript}, slow=True
    )
    if not smoke.expect_status("下書き：テキストの入力で 200", res, 200):
        return None
    body = res.json()
    vitals = {v["item"]: v["value"] for v in body["draft"]["vitals"]}
    smoke.check("下書き：選んだ患者が返る", body["patient"]["id"] == patient_id)
    smoke.check(
        "下書き：患者の照合が緑",
        body["patient_match"]["level"] == "ok",
        f"level={body['patient_match']['level']}",
    )
    smoke.check(
        "下書き：体温 36.8 が取れる", vitals.get("体温") == "36.8", f"体温={vitals.get('体温')}"
    )
    smoke.check(
        "下書き：呼吸数・SpO2 が抜けとして出る",
        {"呼吸数", "SpO2"} <= set(body["missing"]),
        f"missing={body['missing']}",
    )
    smoke.check("下書き：依頼が1件以上", len(body["draft"]["requests"]) >= 1)
    smoke.check("下書き：二段目の署名が付く", len(body["entail_seals"]) >= 1)
    return body


def verify_changed_number(smoke: Smoke, drafted: dict[str, Any]) -> None:
    """S の1文目の数字を変え、`number_not_in_evidence` が出るかを確かめる（entail=false）。

    本物の Gemini の文には数字がないこともあるので、そのときは根拠にない数（999）を足す。
    """
    draft = deepcopy(drafted["draft"])
    sentence = draft["soap"]["S"][0]
    if re.search(r"\d", sentence["text"]):
        sentence["text"] = re.sub(r"\d+", lambda m: str(int(m[0]) + 3), sentence["text"], count=1)
    else:
        sentence["text"] += "（999回）"
    body = {"utterances": drafted["utterances"], "draft": draft, "entail": False}
    res = smoke.request("POST", "/api/verify", json=body)
    if not smoke.expect_status("照合：数字を変えた下書きで 200", res, 200):
        return
    result = res.json()
    codes = {(c["path"], c["code"]) for c in result["checks"]}
    smoke.check(
        "照合：変えた数字が number_not_in_evidence になる",
        ("soap.S[0]", "number_not_in_evidence") in codes,
        f"checks={sorted(codes)}",
    )
    smoke.check("照合：entail=false では署名を返さない", result["entail_seals"] == [])


def verify_entail(smoke: Smoke, drafted: dict[str, Any]) -> None:
    """二段目をかけ直す（entail=true）。署名つきの判定が返るかを確かめる。"""
    body = {"utterances": drafted["utterances"], "draft": drafted["draft"], "entail": True}
    res = smoke.request("POST", "/api/verify", json=body, slow=True)
    if smoke.expect_status("照合：entail=true で 200", res, 200):
        smoke.check("照合：entail=true で署名が返る", len(res.json()["entail_seals"]) >= 1)


def confirm(smoke: Smoke, drafted: dict[str, Any]) -> dict[str, Any] | None:
    """受け取った署名をそのまま返し、看護師の依頼を1件足して確定する（A-12）。

    確定の応答（record_id・タスクの id）を返す。
    """
    stop_paths = sorted({c["path"] for c in drafted["checks"] if c["level"] == "stop"})
    draft = deepcopy(drafted["draft"])
    draft["requests"].append(nurse_request(drafted))
    body = {
        "confirm_id": f"smoke-{int(time.time())}",
        "patient_id": drafted["patient"]["id"],
        "patient_confirmed": drafted["patient_match"]["level"] != "ok",
        "utterances": drafted["utterances"],
        "draft": draft,
        "entail_seals": drafted["entail_seals"],
        "draft_token": drafted["draft_token"],
        "decisions": [{"path": p, "action": "keep"} for p in stop_paths],
    }
    res = smoke.request("POST", "/api/records", json=body, slow=True)
    if not smoke.expect_status("確定：200", res, 200):
        return None
    record = res.json()
    room = drafted["patient"]["room"]
    smoke.check("確定：カルテ用の文に部屋番号が入る", f"{room}号室" in record["chart_text"])
    tasks = record["tasks_created"]
    smoke.check(
        "確定：依頼の数（看護師が足した分を含む）だけタスクができる",
        len(tasks) == len(draft["requests"]),
        f"{len(tasks)}件",
    )
    return record


def records_list_and_detail(smoke: Smoke, drafted: dict[str, Any], record_id: str) -> None:
    """確定した記録が一覧に出て、詳細で根拠の発言とカルテ用の文が取れるかを確かめる。"""
    patient_id = drafted["patient"]["id"]
    res = smoke.request("GET", "/api/records", params={"patient_id": patient_id})
    if smoke.expect_status("記録：一覧で 200", res, 200):
        listed = [r["record_id"] for r in res.json()["records"]]
        smoke.check("記録：確定した記録が一覧の先頭に出る", listed[:1] == [record_id])
    res = smoke.request("GET", f"/api/records/{record_id}")
    if not smoke.expect_status("記録：詳細で 200", res, 200):
        return
    detail = res.json()["record"]
    utterance_ids = {u["id"] for u in drafted["utterances"]}
    saved_ids = {u["id"] for u in detail["evidence_utterances"]}
    smoke.check(
        "記録：根拠の発言だけが残り、会話の全文は返らない（P-02）",
        "utterances" not in detail and 0 < len(saved_ids) < len(utterance_ids),
        f"{len(saved_ids)}/{len(utterance_ids)}件",
    )
    smoke.check("記録：カルテ用の文が返る", detail["chart_text"].startswith("【"))


def tasks_and_done(smoke: Smoke, task_ids: list[str]) -> None:
    """作られたタスクが一覧に出て、患者の発言が入り、済みにできるかを確かめる。"""
    res = smoke.request("GET", "/api/tasks", params={"status": "open"})
    if not smoke.expect_status("タスク：一覧で 200", res, 200):
        return
    listed = {t["id"]: t for t in res.json()["tasks"]}
    mine = [listed[i] for i in task_ids if i in listed]
    smoke.check("タスク：確定で作ったタスクが一覧に出る", len(mine) == len(task_ids) > 0)
    smoke.check(
        "タスク：patient_words に患者の発言が入る",
        bool(mine) and all(t["patient_words"] for t in mine),
    )
    if not mine:
        return
    res = smoke.request("PATCH", f"/api/tasks/{mine[0]['id']}", json={"status": "done"})
    if smoke.expect_status("タスク：済みにして 200", res, 200):
        task = res.json()["task"]
        smoke.check(
            "タスク：status が done・done_at が入る",
            task["status"] == "done" and task["done_at"] is not None,
        )


def run_flow(smoke: Smoke) -> bool:
    """下書きからタスクまでを順に回す。確定を呼んだら True（live なら保存が残りうる）。"""
    drafted = create_draft(smoke)
    if drafted is None:
        smoke.skip("照合・確定・タスク", "下書きが NG")
        return False
    verify_changed_number(smoke, drafted)
    verify_entail(smoke, drafted)
    confirmed = confirm(smoke, drafted)
    if confirmed is None:
        smoke.skip("記録・タスク", "確定が NG")
        return True
    records_list_and_detail(smoke, drafted, confirmed["record_id"])
    task_ids = confirmed["tasks_created"]
    if task_ids:
        check_nurse_task(smoke, task_ids)
        check_labels(smoke, drafted, task_ids)
        check_assignment(smoke, drafted, task_ids)
        tasks_and_done(smoke, task_ids)
    else:
        smoke.skip("タスク", "タスクができなかった")
    create_task_directly(smoke, drafted["patient"]["id"])
    return True
