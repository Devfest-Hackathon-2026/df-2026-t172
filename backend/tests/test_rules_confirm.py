"""docs/design/rules.md の決まりのうち、確定と保存にかかわるもの（MODE=mock で確かめる）。"""

from datetime import datetime, time, timedelta

import pytest
from fastapi.testclient import TestClient

from app.main import create_app
from app.services.clock import JST
from tests.helpers import HEADERS, make_services, make_settings, post_text_draft, record_body


@pytest.fixture
def app_and_store() -> tuple[TestClient, dict]:
    """確定した記録をのぞけるように、保存先（メモリ）も返す。"""
    services = make_services()
    client = TestClient(create_app(make_settings("mock"), services))
    return client, services.store._records  # テストでだけ中をのぞく


def _confirm(client: TestClient, body: dict) -> dict:
    res = client.post("/api/records", json=body, headers=HEADERS)
    assert res.status_code == 200, res.text
    return res.json()


@pytest.mark.parametrize(("patient_id", "level"), [("p310", "confirm"), ("p303", "stop")])
def test_S03_yellow_and_red_need_patient_confirmed(
    mock_client: TestClient, patient_id: str, level: str
) -> None:
    """S-03：黄・赤は、看護師が確かめるまで確定できない（409）。"""
    draft = post_text_draft(mock_client, patient_id)
    assert draft["patient_match"]["level"] == level
    res = mock_client.post("/api/records", json=record_body(draft), headers=HEADERS)
    assert res.status_code == 409 and res.json()["error"]["code"] == "patient_not_confirmed"
    _confirm(mock_client, record_body(draft, patient_confirmed=True))


def test_S04_red_confirmed_without_reason_is_noted(app_and_store: tuple) -> None:
    """S-04：赤でも理由の入力なしで確定でき、記録に「看護師が確認」と残る。"""
    client, records = app_and_store
    draft = post_text_draft(client, "p303")
    body = _confirm(client, record_body(draft, patient_confirmed=True))
    assert records[body["record_id"]]["patient_check"] == {
        "level": "stop",
        "confirmed_by_nurse": True,
        "note": "照合で食い違いあり→看護師が確認",
    }


def test_S06_R01_chart_text_format(mock_client: TestClient) -> None:
    """S-06・R-01：先頭に患者・日時、次にバイタル（T・BP・P・R・SpO2）、S)→O)→A)→P)。"""
    draft = post_text_draft(mock_client, "p312")
    draft["draft"]["soap"]["A"], draft["draft"]["soap"]["P"] = "ふらつきあり", "歩行時見守り"
    lines = _confirm(mock_client, record_body(draft))["chart_text"].split("\n")
    assert lines[0].startswith("【312号室A 小林 正雄様】")
    assert lines[1] == "T 36.6℃ BP 118/70 P 82 R 16 SpO2 97%"
    assert [line[:3] for line in lines[2:]] == ["S) ", "O) ", "A) ", "P) "]
    assert lines[4:] == ["A) ふらつきあり", "P) 歩行時見守り"]


def test_A05_stop_checks_must_be_decided(mock_client: TestClient) -> None:
    """A-05：「止める」が残っていたら 409。画面が checks を送らなくてもサーバーが止める。"""
    draft = post_text_draft(mock_client, "p302")
    draft["draft"]["vitals"][0]["value"] = "37.9"
    res = mock_client.post("/api/records", json=record_body(draft, checks=[]), headers=HEADERS)
    assert res.status_code == 409 and res.json()["error"]["code"] == "undecided_checks"


def test_A06_kept_unsupported_sentence_is_marked_only_in_record(app_and_store: tuple) -> None:
    """A-06：「残す」を選んだ文は記録のデータに印が残り、カルテ用の文には出ない。"""
    client, records = app_and_store
    draft = post_text_draft(client, "p308")  # soap.S[2]「脱水傾向あり。」が二段目で止まる
    decisions = [{"path": "soap.S[0]", "action": "delete"}, {"path": "soap.S[2]", "action": "keep"}]
    body = _confirm(client, record_body(draft, decisions=decisions))
    assert records[body["record_id"]]["kept_after_check"] == [
        {"path": "soap.S[1]", "codes": ["entail_not_supported"], "note": "看護師が確認して残した"}
    ]
    assert "脱水傾向あり。" in body["chart_text"]
    assert "看護師が確認" not in body["chart_text"]


def test_A08_urgency_set_by_rule_or_nurse(mock_client: TestClient) -> None:
    """A-08：緊急度はコードが決める。看護師が変えたら urgency_set_by が nurse。"""
    draft = post_text_draft(mock_client, "p305")
    draft["draft"]["requests"][0]["urgency"] = "said_urgent"  # 看護師が段を上げた
    created = _confirm(mock_client, record_body(draft))["tasks_created"]
    tasks = {t["id"]: t for t in mock_client.get("/api/tasks", headers=HEADERS).json()["tasks"]}
    assert [tasks[i]["urgency_set_by"] for i in created] == ["nurse", "rule"]
    assert tasks[created[1]]["urgency"] == "timed"


def test_P01_P02_audio_and_unused_utterances_are_not_saved(app_and_store: tuple) -> None:
    """P-01・P-02：音声と、根拠でない発言（雑談）・消した要素の根拠だけの発言は保存しない。"""
    client, records = app_and_store
    draft = post_text_draft(client, "p302")
    decisions = [{"path": "requests[0]", "action": "delete"}]  # u15 だけが根拠の依頼
    record = records[_confirm(client, record_body(draft, decisions=decisions))["record_id"]]
    saved = {u["id"]: u for u in record["evidence_utterances"]}
    assert sorted(saved, key=lambda i: int(i[1:])) == ["u7", "u8", "u9", "u11", "u12", "u13", "u14"]
    assert saved["u9"] == {
        "id": "u9",
        "speaker": "patient",
        "text": "傷がさ、夜中ちょっとズキズキして、あんまり眠れなかったんだよね",
    }
    assert "u15" not in saved and "u6" not in saved  # 消した依頼の根拠・雑談（孫のサッカー）
    assert "utterances" not in record and "audio" not in record
    assert not any(isinstance(v, bytes) for v in record.values())


def test_P03_expires_at_next_midnight(app_and_store: tuple) -> None:
    """P-03：記録とタスクは翌日0時（日本時間）に消える期限を持つ。"""
    client, records = app_and_store
    draft = post_text_draft(client, "p305")
    record = records[_confirm(client, record_body(draft))["record_id"]]
    created: datetime = record["created_at"]
    tomorrow = created.astimezone(JST).date() + timedelta(days=1)
    assert record["expires_at"] == datetime.combine(tomorrow, time(0), tzinfo=JST)


def test_A01_draft_alone_saves_nothing(app_and_store: tuple) -> None:
    """A-01：下書きを作っただけでは何も保存しない。保存は確定（POST /api/records）だけ。"""
    client, records = app_and_store
    post_text_draft(client, "p305")
    assert records == {}


def test_R02_request_needs_patient_utterance(mock_client: TestClient) -> None:
    """R-02：依頼は患者の発言を根拠にしたものだけ（看護師の「持ってきますね」は止める）。"""
    draft = post_text_draft(mock_client, "p302")
    draft["draft"]["requests"][0]["evidence"] = ["u16"]  # 看護師「あとで持ってきますね」
    body = {"utterances": draft["utterances"], "draft": draft["draft"]}
    checks = mock_client.post("/api/verify", json=body, headers=HEADERS).json()["checks"]
    assert ("requests[0]", "speaker_mismatch") in {(c["path"], c["code"]) for c in checks}


def test_S06_full_name_in_tasks_and_record_list(app_and_store: tuple) -> None:
    """S-06：表示用のフルネームがタスクと記録の一覧にも入る（照合は名字のまま）。"""
    client, _ = app_and_store
    draft = post_text_draft(client, "p305")
    _confirm(client, record_body(draft))
    tasks = client.get("/api/tasks", headers=HEADERS).json()["tasks"]
    assert {t["full_name"] for t in tasks if t["patient_id"] == "p305"} == {"佐藤 和夫"}
    records = client.get("/api/records", headers=HEADERS).json()["records"]
    assert records[0]["full_name"] == "佐藤 和夫"
