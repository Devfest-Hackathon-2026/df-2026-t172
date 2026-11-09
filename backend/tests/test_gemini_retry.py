"""Gemini のタイムアウトと1回の再試行（C-05・P-04）。本物の Gemini は呼ばない。"""

import json
import logging
from types import SimpleNamespace as NS
from typing import Any

import pytest
from fastapi.testclient import TestClient
from google.genai import errors

from app.live.gemini_vertex import TIMEOUT_SECONDS, VertexGemini
from app.main import create_app
from tests.fakes import S1_TRANSCRIPT, FakeSpeech
from tests.helpers import HEADERS, SCENARIOS, make_services, make_settings, utterances_of

DRAFT_JSON = json.dumps(SCENARIOS["s1"]["gemini_draft"])
SECRET = "傷がさ、夜中ちょっとズキズキして"


def _api_error(code: int) -> errors.APIError:
    body = {"error": {"code": code, "message": SECRET, "status": "X"}}
    return (errors.ServerError if code >= 500 else errors.ClientError)(code, body)


class ScriptedModels:
    """決めた順に、例外か応答の文を返す generate_content。"""

    def __init__(self, *outcomes: Exception | str):
        self.outcomes = list(outcomes)
        self.calls: list[dict[str, Any]] = []

    def generate_content(self, **kwargs: Any) -> Any:
        self.calls.append(kwargs)
        outcome = self.outcomes.pop(0)
        if isinstance(outcome, Exception):
            raise outcome
        usage = NS(prompt_token_count=10, candidates_token_count=10, thoughts_token_count=0)
        return NS(text=outcome, usage_metadata=usage)


def _gemini(*outcomes: Exception | str) -> tuple[VertexGemini, ScriptedModels, list[float]]:
    models, waits = ScriptedModels(*outcomes), []
    gemini = VertexGemini(
        "p", "global", "gemini-3.5-flash", client=NS(models=models), sleep=waits.append
    )
    return gemini, models, waits


def _failures(caplog: pytest.LogCaptureFixture) -> list[dict[str, Any]]:
    entries = [json.loads(r.getMessage()) for r in caplog.records if r.name == "app"]
    return [e for e in entries if e["event"] == "gemini_failed"]


@pytest.mark.parametrize(
    "first_failure",
    [_api_error(503), _api_error(429), '{"vitals": "壊れた形"}'],
    ids=["503", "429", "json_validation"],
)
def test_C05_retries_once_after_a_short_wait(
    first_failure: Exception | str, caplog: pytest.LogCaptureFixture
) -> None:
    """C-05：429・503・JSON の形の崩れは、少し待って1回だけ呼び直す。"""
    gemini, models, waits = _gemini(first_failure, DRAFT_JSON)
    with caplog.at_level(logging.INFO):
        draft = gemini.generate_draft(utterances_of("s1"))
    assert draft.vitals[0].value == "36.8"
    assert len(models.calls) == 2 and len(waits) == 1 and 1 <= waits[0] <= 2
    [failure] = _failures(caplog)
    assert failure["will_retry"] is True and failure["attempt"] == 1


def test_C05_second_failure_is_raised_with_safe_log(caplog: pytest.LogCaptureFixture) -> None:
    """C-05・P-04：2回目も失敗したら投げる。ログは目的・モデル・秒・状態コードだけ。"""
    gemini, models, _ = _gemini(_api_error(503), _api_error(503))
    with caplog.at_level(logging.INFO), pytest.raises(errors.ServerError):
        gemini.generate_draft(utterances_of("s1"))
    assert len(models.calls) == 2
    first, second = _failures(caplog)
    assert first["will_retry"] is True
    assert second == {
        "severity": "ERROR",
        "event": "gemini_failed",
        "purpose": "draft",
        "model": "gemini-3.5-flash",
        "seconds": second["seconds"],
        "status": 503,
        "error_type": "ServerError",
        "attempt": 2,
        "will_retry": False,
    }
    assert SECRET not in "\n".join(r.getMessage() for r in caplog.records)


def test_C05_other_failures_are_not_retried() -> None:
    """C-05：待っても変わらない失敗（400 など）は呼び直さない。"""
    gemini, models, waits = _gemini(_api_error(400))
    with pytest.raises(errors.ClientError):
        gemini.generate_draft(utterances_of("s1"))
    assert len(models.calls) == 1 and waits == []


def test_C05_each_call_has_a_timeout() -> None:
    """C-05：1回の呼び出しは30秒で打ち切る（API にはミリ秒で渡す）。"""
    gemini, models, _ = _gemini(DRAFT_JSON)
    gemini.generate_draft(utterances_of("s1"))
    assert models.calls[0]["config"].http_options.timeout == TIMEOUT_SECONDS * 1000 == 30_000


def test_C05_draft_is_502_after_two_failures_not_mock() -> None:
    """C-05：2回とも失敗したら 502 を返し、モックの結果には切り替えない。"""
    gemini, models, _ = _gemini(_api_error(503), _api_error(503))
    client = TestClient(create_app(make_settings("live"), make_services(gemini, FakeSpeech())))
    body = {"patient_id": "p302", "transcript": S1_TRANSCRIPT}
    res = client.post("/api/drafts", json=body, headers=HEADERS)
    assert res.status_code == 502 and res.json()["error"]["code"] == "draft_failed"
    assert len(models.calls) == 2
