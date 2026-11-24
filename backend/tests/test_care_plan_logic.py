"""看護計画の印を消す・確かめる・ログの数（care-plan-soap の要件4・6・9）。"""

import json
import logging
from typing import Any

import pytest

from app.errors import ApiError
from app.models.care_plan import CarePlan
from app.models.draft import Draft, Soap, SoapSentence
from app.services.care_plan import (
    clear_plan_ids,
    ensure_known_care_plans,
    plan_log_fields,
    unknown_plan_paths,
)
from app.services.mock_data import load_mock_draft, load_patients, load_scenarios

P305_PLANS = [CarePlan(id="cp04", label="#急性疼痛"), CarePlan(id="cp05", label="#活動耐性低下")]


def _s(text: str, plan_id: str | None = None, added_by: str = "ai") -> SoapSentence:
    return SoapSentence(text=text, evidence=[], added_by=added_by, plan_id=plan_id)


def _draft(s: list[SoapSentence], o: list[SoapSentence] | None = None) -> Draft:
    return Draft(soap=Soap(S=s, O=o or []))


# Feature: care-plan-soap, Property 3: 下書きの看護計画の印を消す
@pytest.mark.parametrize("scenario_id", [sc["id"] for sc in load_scenarios()])
def test_A14_clear_plan_ids(scenario_id: str) -> None:
    draft = load_mock_draft(scenario_id).draft
    marked = draft.model_copy(deep=True)
    for s in marked.soap.S + marked.soap.O:
        s.plan_id = "cp04"
    before = marked.model_dump()
    cleared = clear_plan_ids(marked)
    assert all(s.plan_id is None for s in cleared.soap.S + cleared.soap.O)
    assert marked.model_dump() == before  # 元の下書きは変えない
    strip = {"soap": {"S": {"__all__": {"plan_id"}}, "O": {"__all__": {"plan_id"}}}}
    assert cleared.model_dump(exclude=strip) == marked.model_dump(exclude=strip)


# Feature: care-plan-soap, Property 5: 選んだ患者の看護計画にない plan_id の文をちょうど見つける
def test_R03_unknown_plan_paths() -> None:
    draft = _draft(
        [_s("a", "cp04"), _s("b"), _s("c", "cp01"), _s("d", "cp99"), _s("e", "CP04")],
        [_s("f", "cp02", added_by="nurse"), _s("g", "cp05")],
    )
    assert unknown_plan_paths(draft, P305_PLANS) == [
        "soap.S[2]",
        "soap.S[3]",
        "soap.S[4]",
        "soap.O[0]",
    ]
    assert unknown_plan_paths(draft.model_copy(update={"soap": Soap()}), P305_PLANS) == []


@pytest.mark.parametrize(
    ("draft", "places"),
    [
        (_draft([_s("a"), _s("b", "cp01")]), "（S 2文目）"),
        (_draft([_s("a", "cp99")], [_s("b", "cp01")]), "（S 1文目、O 1文目）"),
        (
            _draft([_s(str(i), "cp99") for i in range(7)]),
            "（S 1文目、S 2文目、S 3文目、S 4文目、S 5文目 ほか2件）",
        ),
    ],
)
def test_R03_unknown_care_plan_message(draft: Draft, places: str) -> None:
    with pytest.raises(ApiError) as caught:
        ensure_known_care_plans(draft, P305_PLANS)
    err = caught.value
    assert (err.status, err.code) == (422, "unknown_care_plan")
    assert places in err.message
    for word in ("#急性疼痛", "急性疼痛", "cp99", "cp01"):
        assert word not in err.message


def test_R03_known_plans_pass() -> None:
    ensure_known_care_plans(_draft([_s("a", "cp04"), _s("b")], [_s("c", "cp05")]), P305_PLANS)


def _app_logs(caplog: pytest.LogCaptureFixture) -> list[dict[str, Any]]:
    return [json.loads(r.getMessage()) for r in caplog.records if r.name == "app"]


def test_P04_unknown_care_plan_log_line(caplog: pytest.LogCaptureFixture) -> None:
    with caplog.at_level(logging.INFO), pytest.raises(ApiError):
        ensure_known_care_plans(_draft([_s("a", "cp99"), _s("b", "cp01")]), P305_PLANS)
    [line] = _app_logs(caplog)
    assert line == {
        "severity": "WARNING",
        "event": "record_rejected",
        "code": "unknown_care_plan",
        "unknown_plan_sentences": 2,
    }


# Feature: care-plan-soap, Property 9: 確定のログの数
@pytest.mark.parametrize(
    ("draft", "plans", "expected"),
    [
        (_draft([]), P305_PLANS, ((0, 0), (0, 0), 0)),
        (_draft([_s("a"), _s("b")], [_s("c")]), P305_PLANS, ((0, 0), (2, 1), 0)),
        (_draft([_s("a", "cp04")], [_s("c", "cp05")]), P305_PLANS, ((1, 1), (0, 0), 2)),
        (_draft([_s("a", "cp04"), _s("b", "cp04")]), P305_PLANS, ((2, 0), (0, 0), 1)),
        (_draft([_s("  ", "cp05"), _s("a")]), P305_PLANS, ((1, 0), (1, 0), 0)),
        (_draft([_s("a"), _s("b")]), [], ((0, 0), (2, 0), 0)),
    ],
)
def test_P04_confirm_log_plan_counts(
    draft: Draft, plans: list[CarePlan], expected: tuple[tuple[int, int], tuple[int, int], int]
) -> None:
    fields = plan_log_fields(draft, plans)
    (sp, op), (su, ou), used = expected
    assert fields == {
        "plan_sentences": {"S": sp, "O": op},
        "unplanned_sentences": {"S": su, "O": ou},
        "plans_used": used,
        "plans_available": len(plans),
    }
    assert sp + su == len(draft.soap.S) and op + ou == len(draft.soap.O)
    assert 0 <= used <= len(plans)
    assert "cp04" not in json.dumps(fields)


def test_seed_roster_is_loaded() -> None:
    assert [p.id for p in load_patients()][:1] == ["p302"]
