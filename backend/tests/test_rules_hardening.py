"""11/8 の批判で足した守り：二段目の結果の署名（A-04・A-05）、ログ（P-04・SEC-05）ほか。"""

import logging
from typing import Any

import pytest
from fastapi import APIRouter
from fastapi.testclient import TestClient

from app.config import ConfigError, load_settings
from app.main import create_app
from tests.fakes import S1_TRANSCRIPT, FakeGemini
from tests.helpers import HEADERS, make_services, make_settings, post_text_draft, record_body


def _confirm(client: TestClient, body: dict[str, Any]) -> Any:
    return client.post("/api/records", json=body, headers=HEADERS)


def test_A04_record_cannot_drop_entail_checks(mock_client: TestClient) -> None:
    """A-04・A-05：二段目で止まった文は、画面が結果を送らなくても・偽っても確定できない。"""
    draft = post_text_draft(mock_client, "p308")  # soap.S[2] が二段目で止まる
    dropped = record_body(draft, entail_seals=[])
    forged = record_body(
        draft,
        entail_seals=[
            {**s, "verdict": "supported"} if s["path"] == "soap.S[2]" else s
            for s in draft["entail_seals"]
        ],
    )
    for body in (dropped, forged):
        res = _confirm(mock_client, body)
        assert res.status_code == 409 and res.json()["error"]["code"] == "undecided_checks"
    keep = [{"path": "soap.S[2]", "action": "keep"}]
    assert _confirm(mock_client, record_body(draft, decisions=keep)).status_code == 200


def test_A04_sealed_results_are_not_judged_again() -> None:
    """A-04：署名で裏付けられた文は、確定のときに Gemini を呼び直さない。"""
    gemini = FakeGemini()
    client = TestClient(create_app(make_settings("live"), make_services(gemini)))
    draft = post_text_draft(client, "p302", S1_TRANSCRIPT)
    assert gemini.calls == ["draft", "judge"]
    assert _confirm(client, record_body(draft)).status_code == 200
    assert gemini.calls == ["draft", "judge"]


def test_A04_edited_sentence_is_judged_again_at_confirm() -> None:
    """A-04：直した文は署名が合わなくなり、確定のときに二段目を呼び直す。"""
    gemini = FakeGemini()
    client = TestClient(create_app(make_settings("live"), make_services(gemini)))
    draft = post_text_draft(client, "p302", S1_TRANSCRIPT)
    draft["draft"]["soap"]["S"][0]["text"] += "（直した）"
    res = _confirm(client, record_body(draft))
    assert gemini.calls == ["draft", "judge", "judge"]
    assert res.status_code == 409  # 見本にない文は「判断できない」で止まる


def test_P04_SEC05_unexpected_error_logs_no_body_or_traceback(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """P-04・SEC-05：思わぬ例外でも、ログに本文とスタックトレースが出ず、投げ直さない。"""
    secret = "傷がさ、夜中ちょっとズキズキして"
    app = create_app(make_settings("mock"), make_services())
    router = APIRouter()

    @router.get("/api/boom")
    def boom() -> None:
        raise ValueError(secret)

    app.include_router(router)
    with caplog.at_level(logging.DEBUG):
        res = TestClient(app).get("/api/boom")  # 投げ直されていれば、ここで例外になる
    assert res.status_code == 500 and res.json()["error"]["code"] == "internal_error"
    assert secret not in "\n".join(r.getMessage() for r in caplog.records)
    assert not any(r.exc_info for r in caplog.records)


def test_P04_timing_accepts_only_iso_times(mock_client: TestClient) -> None:
    """P-04：計測用の時刻は ISO 8601 だけ（ログに任意の文字列を出さない）。"""
    draft = post_text_draft(mock_client, "p302")
    body = record_body(draft, timing={"recording_started": "傷がズキズキ"})
    assert _confirm(mock_client, body).status_code == 422


def test_SEC05_api_docs_are_not_public(mock_client: TestClient) -> None:
    """SEC-05：公開 URL で API の一覧を見せない。"""
    for url in ("/docs", "/redoc", "/openapi.json"):
        assert mock_client.get(url).status_code == 404


def test_SEC01_short_passcode_stops_startup(monkeypatch: pytest.MonkeyPatch) -> None:
    """SEC-01：合言葉が12文字より短ければ起動しない。"""
    monkeypatch.setenv("PASSCODE", "x" * 11)
    with pytest.raises(ConfigError):
        load_settings()


def test_A01_same_confirm_id_overwrites_instead_of_duplicating() -> None:
    """A-01：二重の確定（同じ confirm_id）は上書きし、タスクを重ねない。"""
    services = make_services()
    client = TestClient(create_app(make_settings("mock"), services))
    draft = post_text_draft(client, "p302")
    body = record_body(draft, confirm_id="c_double")
    first, second = _confirm(client, body).json(), _confirm(client, body).json()
    assert first["record_id"] == second["record_id"]
    assert first["tasks_created"] == second["tasks_created"]
    saved = services.store._tasks.values()  # テストでだけ中をのぞく
    assert sum(t["record_id"] == first["record_id"] for t in saved) == len(first["tasks_created"])


def test_R01_sentence_without_period_gets_one(mock_client: TestClient) -> None:
    """R-01：句点のない文には、カルテ用の文で「。」を足す（文がつながらないように）。"""
    draft = post_text_draft(mock_client, "p302")
    draft["draft"]["soap"]["S"] = [
        {"text": "痛い", "evidence": draft["draft"]["soap"]["S"][0]["evidence"]},
        {"text": "眠れた？", "evidence": draft["draft"]["soap"]["S"][0]["evidence"]},
    ]
    decisions = [{"path": "soap.S[0]", "action": "keep"}, {"path": "soap.S[1]", "action": "keep"}]
    res = _confirm(mock_client, record_body(draft, decisions=decisions))
    assert "S) 痛い。眠れた？" in res.json()["chart_text"].split("\n")
