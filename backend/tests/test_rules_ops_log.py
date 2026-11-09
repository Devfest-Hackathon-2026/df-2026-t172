"""確定のときの操作記録（設計 9章）。ログは時刻・色・数だけ（P-04）。"""

import json
import logging
from typing import Any

import pytest
from fastapi.testclient import TestClient

from app.main import create_app
from tests.fakes import S1_TRANSCRIPT, FakeGemini
from tests.helpers import HEADERS, make_services, make_settings, post_text_draft, record_body


def _confirmed_log(caplog: pytest.LogCaptureFixture) -> dict[str, Any]:
    entries = [json.loads(r.getMessage()) for r in caplog.records if r.name == "app"]
    return next(e for e in entries if e["event"] == "record_confirmed")


def test_P04_confirm_log_has_counts_and_colors_only(
    mock_client: TestClient, caplog: pytest.LogCaptureFixture
) -> None:
    """P-04・S-03：照合の色・確かめたか・文と依頼の数・画面の数を出し、会話の文と患者名は出さない。"""
    draft = post_text_draft(mock_client, "p310")  # 患者の照合が黄（confirm）
    body = record_body(draft, patient_confirmed=True, ui_counts={"edited": 2, "evidence_taps": 5})
    with caplog.at_level(logging.INFO):
        res = mock_client.post("/api/records", json=body, headers=HEADERS)
    assert res.status_code == 200, res.text
    log = _confirmed_log(caplog)
    soap = draft["draft"]["soap"]
    assert log["patient_match"] == "confirm" and log["patient_confirmed"] is True
    assert log["sentences"] == {"S": len(soap["S"]), "O": len(soap["O"])}
    assert log["requests"] == len(draft["draft"]["requests"])
    assert log["entail_rejudged"] == 0  # 署名で裏付けられているので呼び直さない
    assert log["ui_counts"] == {"edited": 2, "evidence_taps": 5}
    line = json.dumps(log, ensure_ascii=False)
    assert draft["patient"]["name"] not in line
    assert not any(u["text"] in line for u in draft["utterances"] if len(u["text"]) > 3)


def test_P04_confirm_log_counts_rejudged_sentences(caplog: pytest.LogCaptureFixture) -> None:
    """A-04：確定のときに二段目を呼び直した文の数を出す（直した文が1つなら1）。"""
    client = TestClient(create_app(make_settings("live"), make_services(FakeGemini())))
    draft = post_text_draft(client, "p302", S1_TRANSCRIPT)
    draft["draft"]["soap"]["S"][0]["text"] += "（直した）"
    decisions = [{"path": "soap.S[0]", "action": "keep"}]
    with caplog.at_level(logging.INFO):
        res = client.post(
            "/api/records", json=record_body(draft, decisions=decisions), headers=HEADERS
        )
    assert res.status_code == 200, res.text
    assert _confirmed_log(caplog)["entail_rejudged"] == 1


@pytest.mark.parametrize(
    "ui_counts",
    [
        {"edited": "田中"},  # 文字列（患者名を入れられる）
        {"edited": "2"},  # 数に読める文字列も受けない
        {"edited": True},
        {"edited": -1},
        {"edited": 1.5},
        {"memo": 1},  # 決めていないキー
    ],
)
def test_P04_ui_counts_accept_only_known_non_negative_integers(
    mock_client: TestClient, ui_counts: dict[str, Any]
) -> None:
    """P-04：ui_counts は決めたキーの、0以上の整数だけ（ほかは 422）。"""
    draft = post_text_draft(mock_client, "p302")
    body = record_body(draft, ui_counts=ui_counts)
    assert mock_client.post("/api/records", json=body, headers=HEADERS).status_code == 422
