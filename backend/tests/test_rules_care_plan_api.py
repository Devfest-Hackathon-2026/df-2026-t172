"""看護計画の API（care-plan-soap の要件2・4・6・7・9）。外のサービスは差し替えて動かす。"""

import json
from typing import Any

import pytest
from fastapi.testclient import TestClient

from app.main import create_app
from app.models.api import DraftResponse
from app.routes import drafts as drafts_route
from app.services.mock_data import load_mock_draft, load_patients
from tests.fakes import FakeGemini
from tests.helpers import HEADERS, make_services, make_settings, post_text_draft

ROSTER = {p.id: p for p in load_patients()}


def _plans(patient_id: str) -> list[dict[str, str]]:
    return [c.model_dump() for c in ROSTER[patient_id].care_plans]


def _live(gemini: Any = None) -> TestClient:
    return TestClient(create_app(make_settings("live"), make_services(gemini or FakeGemini())))


def test_S08_patients_return_care_plans(mock_client: TestClient) -> None:
    patients = mock_client.get("/api/patients", headers=HEADERS).json()["patients"]
    assert {p["id"]: p["care_plans"] for p in patients} == {pid: _plans(pid) for pid in ROSTER}


def test_S08_patients_care_plans_come_from_roster_not_store() -> None:
    """保存先の患者に看護計画がなくても（live の Firestore）、起動時の名簿の値を返す。"""
    services = make_services()
    for p in services.store.list_patients():
        services.store._patients[p.id] = p.model_copy(update={"care_plans": []})  # type: ignore[attr-defined]
    client = TestClient(create_app(make_settings("mock"), services))
    patients = client.get("/api/patients", headers=HEADERS).json()["patients"]
    assert {p["id"]: p["care_plans"] for p in patients} == {pid: _plans(pid) for pid in ROSTER}


def test_S08_assignee_change_keeps_care_plans(mock_client: TestClient) -> None:
    body = {"assigned_to": "n04", "care_plans": [{"id": "cp99", "label": "#書き換え"}]}
    res = mock_client.patch("/api/patients/p305", json=body, headers=HEADERS)
    assert res.status_code == 200, res.text
    assert res.json()["patient"]["care_plans"] == _plans("p305")
    patients = mock_client.get("/api/patients", headers=HEADERS).json()["patients"]
    assert {p["id"]: p["care_plans"] for p in patients} == {pid: _plans(pid) for pid in ROSTER}


def _all_plan_ids(draft: dict[str, Any]) -> list[Any]:
    soap = draft["draft"]["soap"]
    return [s.get("plan_id", "missing") for s in soap["S"] + soap["O"]]


def test_A14_draft_plan_ids_null_and_patient_care_plans(mock_client: TestClient) -> None:
    mock = post_text_draft(mock_client, "p302")
    assert mock["patient"]["care_plans"] == _plans("p302")
    assert _all_plan_ids(mock) and set(_all_plan_ids(mock)) == {None}
    live = post_text_draft(_live(), "p305", "看護師: おはようございます\n患者: おはよう")
    assert live["patient"]["care_plans"] == _plans("p305")
    assert _all_plan_ids(live) and set(_all_plan_ids(live)) == {None}


def test_A14_mock_file_plan_ids_are_reset(
    mock_client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """わざと壊した例：plan_id を書き込んだ見本に差し替えても、下書きはすべて null。"""

    def marked(scenario_id: str) -> DraftResponse:
        response = load_mock_draft(scenario_id)
        for s in response.draft.soap.S + response.draft.soap.O:
            s.plan_id = "cp01"
        return response

    monkeypatch.setattr(drafts_route, "load_mock_draft", marked)
    draft = post_text_draft(mock_client, "p302")
    assert set(_all_plan_ids(draft)) == {None}
    assert "cp01" not in json.dumps(draft["draft"])


# ---- 確定のときの確かめ（要件6・9、決まり R-03） ----

import logging  # noqa: E402

from app.models.record_request import RecordRequest  # noqa: E402
from app.services.clock import now_jst  # noqa: E402
from app.services.confirm import confirm_record  # noqa: E402
from app.services.drafting import EntailRecheck  # noqa: E402
from tests.helpers import record_body  # noqa: E402


def _confirm(client: TestClient, body: dict[str, Any]) -> Any:
    return client.post("/api/records", json=body, headers=HEADERS)


def _with_plan(draft: dict[str, Any], part: str, index: int, plan_id: Any) -> dict[str, Any]:
    draft = json.loads(json.dumps(draft))
    draft["draft"]["soap"][part][index]["plan_id"] = plan_id
    return draft


def _decided(draft: dict[str, Any]) -> list[dict[str, str]]:
    return [{"path": c["path"], "action": "keep"} for c in draft["checks"] if c["level"] == "stop"]


@pytest.mark.parametrize("plan_id", ["cp01", "cp99", "CP04"])
def test_R03_other_patients_plan_is_422(mock_client: TestClient, plan_id: str) -> None:
    """R-03：選んだ患者（p305）の計画にない id は 422。label と送った値は message に出ない。"""
    draft = _with_plan(post_text_draft(mock_client, "p305"), "S", 0, plan_id)
    res = _confirm(mock_client, record_body(draft, decisions=_decided(draft)))
    assert res.status_code == 422, res.text
    err = res.json()["error"]
    assert err["code"] == "unknown_care_plan" and res.json()["mode"] == "mock"
    assert "S 1文目" in err["message"]
    for word in (plan_id, "#急性疼痛", "#活動耐性低下"):
        assert word not in err["message"]


def test_R03_deleted_or_nurse_added_sentence_is_checked(mock_client: TestClient) -> None:
    """R-03：消すと決めた文、看護師が足した文の plan_id も確かめる（決定8）。"""
    draft = _with_plan(post_text_draft(mock_client, "p305"), "S", 0, "cp01")
    deleted = record_body(draft, decisions=[{"path": "soap.S[0]", "action": "delete"}])
    assert _confirm(mock_client, deleted).json()["error"]["code"] == "unknown_care_plan"
    draft = post_text_draft(mock_client, "p305")
    draft["draft"]["soap"]["O"].append(
        {"text": "足した文。", "added_by": "nurse", "plan_id": "cp01"}
    )
    res = _confirm(mock_client, record_body(draft, decisions=_decided(draft)))
    assert res.json()["error"]["code"] == "unknown_care_plan"
    assert "O 1文目" in res.json()["error"]["message"]


def test_R03_live_other_patients_plan_is_422_without_gemini() -> None:
    gemini = FakeGemini()
    client = _live(gemini)
    draft = post_text_draft(client, "p305", "看護師: おはようございます\n患者: 傷が痛い")
    draft["draft"]["soap"]["S"][0]["text"] += "（直した）"  # 確定のときに二段目を呼び直す形
    draft = _with_plan(draft, "S", 0, "cp01")
    calls_before = list(gemini.calls)
    res = _confirm(client, record_body(draft, decisions=[{"path": "soap.S[0]", "action": "keep"}]))
    assert res.status_code == 422 and res.json()["error"]["code"] == "unknown_care_plan"
    assert gemini.calls == calls_before  # 二段目を呼ばない


def test_R03_confirm_uses_roster_care_plans() -> None:
    """R-03：保存先から読んだ（care_plans が空の）患者を渡しても、名簿seed の計画で照らす。"""
    client = TestClient(create_app(make_settings("mock"), make_services()))
    draft = _with_plan(post_text_draft(client, "p305"), "S", 0, "cp05")
    req = RecordRequest.model_validate(record_body(draft, decisions=_decided(draft)))
    empty = ROSTER["p305"].model_copy(update={"care_plans": []})
    confirmed = confirm_record(
        req, empty, list(ROSTER.values()), now_jst(), lambda: EntailRecheck([], 0)
    )
    assert "#活動耐性低下" in confirmed.chart_text.split("\n")


def test_R03_unknown_plan_is_not_saved() -> None:
    services = make_services()
    client = TestClient(create_app(make_settings("mock"), services))
    draft = post_text_draft(client, "p305")
    body = record_body(draft, decisions=_decided(draft))
    assert _confirm(client, body).status_code == 200
    saved = services.store.get_record(f"r_p305_{body['confirm_id']}", now_jst())
    tasks = services.store.list_tasks(None, now_jst())
    again = record_body(_with_plan(draft, "S", 0, "cp99"), confirm_id=body["confirm_id"])
    again["decisions"] = body["decisions"]
    assert _confirm(client, again).status_code == 422
    assert services.store.get_record(f"r_p305_{body['confirm_id']}", now_jst()) == saved
    assert services.store.list_tasks(None, now_jst()) == tasks


def test_R03_checked_before_patient_confirm_and_entail(mock_client: TestClient) -> None:
    """R-03：患者の照合が赤（p303）で確認していない・「止める」を決めていない下書きでも、先に 422。"""
    draft = _with_plan(post_text_draft(mock_client, "p303"), "S", 0, "cp99")
    res = _confirm(mock_client, record_body(draft, patient_confirmed=False, decisions=[]))
    assert res.status_code == 422 and res.json()["error"]["code"] == "unknown_care_plan"


def test_R03_missing_or_null_plan_id_confirms(mock_client: TestClient) -> None:
    draft = post_text_draft(mock_client, "p305")
    for s in draft["draft"]["soap"]["S"] + draft["draft"]["soap"]["O"]:
        s.pop("plan_id", None)
    res = _confirm(mock_client, record_body(draft, decisions=_decided(draft)))
    assert res.status_code == 200, res.text
    record = mock_client.get(f"/api/records/{res.json()['record_id']}", headers=HEADERS).json()
    sentences = record["record"]["soap"]["S"] + record["record"]["soap"]["O"]
    assert sentences and all(s["plan_id"] is None for s in sentences)


@pytest.mark.parametrize("bad", ["", "c" * 41, "cp 01", 5, []])
def test_R03_invalid_plan_id_form_is_invalid_request(mock_client: TestClient, bad: Any) -> None:
    draft = _with_plan(post_text_draft(mock_client, "p305"), "S", 0, bad)
    for path, body in (
        (
            "/api/verify",
            {"utterances": draft["utterances"], "draft": draft["draft"], "entail": False},
        ),
        ("/api/records", record_body(draft, decisions=_decided(draft))),
    ):
        res = mock_client.post(path, json=body, headers=HEADERS)
        assert res.status_code == 422, res.text
        payload = res.json()
        assert payload["error"]["code"] == "invalid_request" and payload["mode"] == "mock"
        assert "plan_id" in payload["error"]["message"]


def test_R03_plan_id_on_other_elements_is_dropped() -> None:
    services = make_services()
    client = TestClient(create_app(make_settings("mock"), services))
    draft = post_text_draft(client, "p302")
    for key in ("vitals", "requests", "manual_needed", "doctor_questions"):
        for item in draft["draft"][key]:
            item["plan_id"] = "cp01"
    res = _confirm(client, record_body(draft, decisions=_decided(draft)))
    assert res.status_code == 200, res.text
    record = services.store.get_record(res.json()["record_id"], now_jst())
    for key in ("vitals", "requests", "manual_needed", "doctor_questions"):
        assert all("plan_id" not in item for item in record[key])
    assert all("plan_id" not in t for t in services.store.list_tasks(None, now_jst()))


def _app_lines(caplog: pytest.LogCaptureFixture) -> list[dict[str, Any]]:
    return [json.loads(r.getMessage()) for r in caplog.records if r.name == "app"]


def test_P04_confirm_log_has_plan_counts(
    mock_client: TestClient, caplog: pytest.LogCaptureFixture
) -> None:
    draft = _with_plan(post_text_draft(mock_client, "p308"), "S", 1, "cp06")
    with caplog.at_level(logging.INFO):
        res = _confirm(mock_client, record_body(draft, decisions=_decided(draft)))
    assert res.status_code == 200, res.text
    [log] = [e for e in _app_lines(caplog) if e["event"] == "record_confirmed"]
    assert log["plan_sentences"] == {"S": 1, "O": 0}
    assert log["unplanned_sentences"]["S"] == log["sentences"]["S"] - 1
    assert (log["plans_used"], log["plans_available"]) == (1, 1)


def test_P04_unknown_care_plan_has_no_confirmed_log(
    mock_client: TestClient, caplog: pytest.LogCaptureFixture
) -> None:
    draft = _with_plan(post_text_draft(mock_client, "p305"), "S", 0, "cp99")
    with caplog.at_level(logging.INFO):
        _confirm(mock_client, record_body(draft, decisions=_decided(draft)))
    lines = _app_lines(caplog)
    assert [e for e in lines if e["event"] == "record_rejected"] == [
        {
            "severity": "WARNING",
            "event": "record_rejected",
            "code": "unknown_care_plan",
            "unknown_plan_sentences": 1,
        }
    ]
    assert not [e for e in lines if e["event"] == "record_confirmed"]


def test_P04_no_care_plan_strings_in_logs(
    mock_client: TestClient, caplog: pytest.LogCaptureFixture
) -> None:
    good = _with_plan(post_text_draft(mock_client, "p305"), "S", 0, "cp04")
    bad = _with_plan(good, "S", 0, "cp99")
    with caplog.at_level(logging.INFO):
        _confirm(mock_client, record_body(good, decisions=_decided(good)))
        _confirm(mock_client, record_body(bad, decisions=_decided(bad)))
    logs = "\n".join(r.getMessage() for r in caplog.records if r.name == "app")
    assert '"record_confirmed"' in logs and '"record_rejected"' in logs
    for p in ROSTER.values():
        for plan in p.care_plans:
            assert plan.id not in logs and plan.label not in logs and plan.label[1:] not in logs
    assert "cp99" not in logs


def test_P03_record_has_no_care_plan_copy() -> None:
    services = make_services()
    client = TestClient(create_app(make_settings("mock"), services))
    draft = _with_plan(post_text_draft(client, "p305"), "S", 0, "cp04")
    res = _confirm(client, record_body(draft, decisions=_decided(draft)))
    assert res.status_code == 200, res.text
    record = services.store.get_record(res.json()["record_id"], now_jst())
    tasks = services.store.list_tasks(None, now_jst())
    stored = json.dumps([record, *tasks], ensure_ascii=False, default=str)
    assert "#急性疼痛" not in stored and "#活動耐性低下" not in stored
    assert '"care_plans"' not in stored


# ---- 保存先（Firestore）は看護計画を持たない（要件2の9） ----

from app.store.firestore_store import FirestoreStore  # noqa: E402
from tests.test_live_clients import FakeFirestore  # noqa: E402


def _live_with_firestore() -> tuple[TestClient, FakeFirestore]:
    db = FakeFirestore()
    services = make_services(FakeGemini())
    services.store = FirestoreStore(db)
    services.store.seed_patients(services.roster)
    return TestClient(create_app(make_settings("live"), services)), db


def test_C07_S08_live_patients_use_roster_care_plans() -> None:
    client, db = _live_with_firestore()
    docs = {key[1]: doc for key, doc in db.data.items() if key[0] == "patients"}
    assert docs and all("care_plans" not in d for d in docs.values())
    assert docs["p305"]["assigned_to"] == "n02"
    patients = client.get("/api/patients", headers=HEADERS).json()["patients"]
    assert {p["id"]: p["care_plans"] for p in patients} == {pid: _plans(pid) for pid in ROSTER}
    res = client.patch("/api/patients/p305", json={"assigned_to": "n04"}, headers=HEADERS)
    assert res.status_code == 200, res.text
    assert res.json()["patient"]["care_plans"] == _plans("p305")


def test_C07_S08_bad_care_plans_in_firestore_are_ignored() -> None:
    """わざと壊した例：Firestore に条件に合わない care_plans を手で入れても、500 にならない。"""
    client, db = _live_with_firestore()
    db.data[("patients", "p305")]["care_plans"] = [{"id": "cp04", "label": "あ" * 101}]
    res = client.get("/api/patients", headers=HEADERS)
    assert res.status_code == 200, res.text
    p305 = next(p for p in res.json()["patients"] if p["id"] == "p305")
    assert p305["care_plans"] == _plans("p305")
    draft = client.post(
        "/api/drafts",
        json={"patient_id": "p305", "transcript": "看護師: おはよう\n患者: おはよう"},
        headers=HEADERS,
    )
    assert draft.status_code == 200, draft.text


# ---- plan_id だけの変更で照合・二段目・記録が変わらない（要件3・4・6・7） ----


def _live_draft(gemini: Any) -> tuple[TestClient, dict[str, Any]]:
    """live（FakeGemini）で、場面1の会話から p302 の下書きを作る（患者の照合は緑）。"""
    from tests.fakes import S1_TRANSCRIPT

    client = _live(gemini)
    return client, post_text_draft(client, "p302", S1_TRANSCRIPT)


def _verify(client: TestClient, draft: dict[str, Any]) -> dict[str, Any]:
    body = {"utterances": draft["utterances"], "draft": draft["draft"], "entail": False}
    res = client.post("/api/verify", json=body, headers=HEADERS)
    assert res.status_code == 200, res.text
    return res.json()


# Feature: care-plan-soap, Property 4: plan_id だけを変えても照合・二段目・記録は同じ
def test_A04_A12_plan_only_change_keeps_checks_and_record() -> None:
    gemini = FakeGemini()
    client, draft = _live_draft(gemini)
    planned = _with_plan(_with_plan(draft, "S", 0, "cp01"), "O", 0, "cp02")
    assert _verify(client, planned) == _verify(client, draft)
    calls = len(gemini.calls)
    res = _confirm(client, record_body(planned, decisions=_decided(planned)))
    assert res.status_code == 200, res.text
    assert gemini.calls[calls:] == []  # 署名が合うので二段目を呼び直さない
    record = client.get(f"/api/records/{res.json()['record_id']}", headers=HEADERS).json()["record"]
    assert [s["text"] for s in record["soap"]["S"]] == [
        s["text"] for s in draft["draft"]["soap"]["S"]
    ]
    assert [s["plan_id"] for s in record["soap"]["S"]][:1] == ["cp01"]
    assert [s["plan_id"] for s in record["soap"]["O"]][:1] == ["cp02"]


def test_A04_edited_sentence_with_plan_is_judged_again(caplog: pytest.LogCaptureFixture) -> None:
    gemini = FakeGemini()
    client, draft = _live_draft(gemini)
    draft["draft"]["soap"]["S"][0]["text"] += "（直した）"
    draft = _with_plan(draft, "S", 0, "cp01")
    calls = len(gemini.calls)
    with caplog.at_level(logging.INFO):
        res = _confirm(
            client, record_body(draft, decisions=[{"path": "soap.S[0]", "action": "keep"}])
        )
    assert res.status_code == 200, res.text
    assert gemini.calls[calls:] == ["judge"]
    [log] = [e for e in _app_lines(caplog) if e["event"] == "record_confirmed"]
    assert log["entail_rejudged"] == 1


def _split_first_s(draft: dict[str, Any], front: str, back: str) -> dict[str, Any]:
    """S の1文目を分ける：前半に直し、後半を同じ欄の最後に、同じ added_by・根拠で足す。"""
    draft = json.loads(json.dumps(draft))
    first = draft["draft"]["soap"]["S"][0]
    tail = {
        "text": back,
        "evidence": list(first["evidence"]),
        "added_by": first["added_by"],
        "plan_id": None,
    }
    first["text"] = front
    draft["draft"]["soap"]["S"].append(tail)
    return draft


def test_A12_split_ai_sentence_is_checked() -> None:
    """A-12：AI の文を分けた後半も AI の要素として照合と二段目にかかり、二段目は1回だけ。"""
    gemini = FakeGemini()
    client, draft = _live_draft(gemini)
    split = _split_first_s(draft, "夜間に創部痛あり。", "あまり眠れなかったとの訴え。")
    tail = f"soap.S[{len(split['draft']['soap']['S']) - 1}]"
    calls = len(gemini.calls)
    decisions = [{"path": "soap.S[0]", "action": "keep"}, {"path": tail, "action": "keep"}]
    res = _confirm(client, record_body(split, decisions=decisions))
    assert res.status_code == 200, res.text
    assert gemini.calls[calls:] == ["judge"]
    # わざと壊した例：後半に根拠の発言にない数を入れると、照合で止まる
    broken = _split_first_s(draft, "夜間に創部痛あり。", "体温は39.9度との訴え。")
    checks = _verify(client, broken)["checks"]
    assert any(c["path"] == tail and c["code"] == "number_not_in_evidence" for c in checks)


class _SpyGemini(FakeGemini):
    """Gemini に渡した引数を、文字列にして覚える。"""

    def __init__(self) -> None:
        super().__init__()
        self.seen: list[str] = []

    def generate_draft(self, utterances: Any) -> Any:
        self.seen.append(repr(utterances))
        return super().generate_draft(utterances)

    def judge(self, targets: Any, utterances: Any) -> Any:
        self.seen.append(repr((targets, utterances)))
        return super().judge(targets, utterances)


def test_A14_A09_care_plans_not_sent_to_gemini() -> None:
    gemini = _SpyGemini()
    client, draft = _live_draft(gemini)
    planned = _with_plan(draft, "S", 0, "cp01")
    body = {"utterances": planned["utterances"], "draft": planned["draft"], "entail": True}
    assert client.post("/api/verify", json=body, headers=HEADERS).status_code == 200
    planned["draft"]["soap"]["S"][0]["text"] += "（直した）"
    res = _confirm(
        client, record_body(planned, decisions=[{"path": "soap.S[0]", "action": "keep"}])
    )
    assert res.status_code == 200, res.text
    sent = "\n".join(gemini.seen)
    assert len(gemini.seen) >= 3  # 下書き・照合・確定の呼び直し
    for p in ROSTER.values():
        for plan in p.care_plans:
            assert plan.id not in sent and plan.label not in sent


# ---- 記録閲覧と見本の場面（要件6の6・6の7・8の12・8の14・10の2） ----

P308_TEXT = "看護師: こんにちは"


def test_R01_record_view_rebuilds_same_chart(mock_client: TestClient) -> None:
    draft = _with_plan(post_text_draft(mock_client, "p308"), "S", 1, "cp06")
    res = _confirm(mock_client, record_body(draft, decisions=_decided(draft)))
    assert res.status_code == 200, res.text
    view = mock_client.get(f"/api/records/{res.json()['record_id']}", headers=HEADERS).json()
    assert view["record"]["chart_text"] == res.json()["chart_text"]
    assert "#体液量不足リスク状態" in res.json()["chart_text"].split("\n")


@pytest.mark.parametrize("change", ["no_plans", "not_in_roster"])
def test_R01_R03_record_view_after_roster_change(change: str) -> None:
    services = make_services()
    client = TestClient(create_app(make_settings("mock"), services))
    draft = _with_plan(post_text_draft(client, "p308"), "S", 1, "cp06")
    res = _confirm(client, record_body(draft, decisions=_decided(draft)))
    assert res.status_code == 200, res.text
    if change == "no_plans":
        services.roster = [
            p.model_copy(update={"care_plans": []}) if p.id == "p308" else p
            for p in services.roster
        ]
    else:
        services.roster = [p for p in services.roster if p.id != "p308"]
    view = client.get(f"/api/records/{res.json()['record_id']}", headers=HEADERS)
    assert view.status_code == 200, view.text
    record = view.json()["record"]
    assert record["soap"]["S"][1]["plan_id"] == "cp06"
    lines = record["chart_text"].split("\n")
    assert lines.count("計画外") == 1 and "#体液量不足リスク状態" not in lines
    sentence = draft["draft"]["soap"]["S"][1]["text"]
    assert record["chart_text"].count(sentence) == 1


def test_R03_old_record_without_plan_id_reads_null() -> None:
    services = make_services()
    client = TestClient(create_app(make_settings("mock"), services))
    draft = post_text_draft(client, "p305")
    res = _confirm(client, record_body(draft, decisions=_decided(draft)))
    record_id = res.json()["record_id"]
    stored = services.store._records[record_id]  # type: ignore[attr-defined]
    for s in stored["soap"]["S"] + stored["soap"]["O"]:
        s.pop("plan_id", None)
    before = json.dumps(stored, default=str, ensure_ascii=False)
    view = client.get(f"/api/records/{record_id}", headers=HEADERS).json()["record"]
    assert all(s["plan_id"] is None for s in view["soap"]["S"] + view["soap"]["O"])
    assert json.dumps(stored, default=str, ensure_ascii=False) == before


@pytest.mark.parametrize(
    ("patient_id", "part", "index", "plan_id", "label"),
    [
        ("p308", "S", 1, "cp06", "#体液量不足リスク状態"),
        ("p302", "O", 0, "cp02", "#感染リスク状態"),
        ("p302", "S", 0, "cp01", "#急性疼痛"),
        ("p303", "S", 0, "cp03", "#急性疼痛"),
        ("p305", "S", 0, "cp05", "#活動耐性低下"),
        ("p312", "S", 0, "cp08", "#転倒転落リスク状態"),
    ],
)
def test_P07_mock_scenarios_have_attachable_sentences(
    mock_client: TestClient, patient_id: str, part: str, index: int, plan_id: str, label: str
) -> None:
    draft = post_text_draft(mock_client, patient_id)
    assert draft["draft"]["soap"][part][index]["text"].strip()
    draft = _with_plan(draft, part, index, plan_id)
    body = record_body(draft, decisions=_decided(draft), patient_confirmed=True)
    res = _confirm(mock_client, body)
    assert res.status_code == 200, res.text
    assert label in res.json()["chart_text"].split("\n")
