"""3回目の批判で見つかった「照合済みなのに誤りが通る」経路（spike/test_edges.py の16件）。"""

from typing import Any

import pytest

from app.checks.entail import entail_checks, entail_targets
from app.checks.verify import verify
from app.models.draft import Draft, Utterance
from app.models.gemini import Verdict, Verdicts


def utt(*rows: tuple[str, str]) -> list[Utterance]:
    """(話者, 文) の並びから発言の列を作る。"""
    return [Utterance(id=f"u{i}", speaker=s, text=t) for i, (s, t) in enumerate(rows, 1)]  # type: ignore[arg-type]


def temperature(value: str, evidence: list[str]) -> dict[str, Any]:
    return {"item": "体温", "value": value, "evidence": evidence}


def stop_messages(draft: Draft, utterances: list[Utterance]) -> str:
    return " ".join(c.message for c in verify(draft, utterances).checks if c.level == "stop")


def warn_messages(draft: Draft, utterances: list[Utterance]) -> str:
    return " ".join(c.message for c in verify(draft, utterances).checks if c.level == "warn")


CORRECTION = utt(
    ("nurse", "体温は36.8度ですね"),
    ("patient", "え、そう？"),
    ("nurse", "読み間違いでした。36.4度です"),
)
YESTERDAY_SAME = utt(("nurse", "36.8度ですね。昨日は37.5度でしたよ"))
YESTERDAY_OTHER = utt(("nurse", "今日は36.8度ですね"), ("nurse", "昨日は37.5度でしたよ"))
PAIN = utt(
    ("patient", "傷が痛くてね"),
    ("nurse", "痛みは10段階でいうとどれくらいですか"),
    ("patient", "4くらいかな"),
)


def test_S07_correction_in_other_utterance_stops_old_value() -> None:
    d = Draft(vitals=[temperature("36.8", ["u1"])])
    assert "最新の値" in stop_messages(d, CORRECTION)


def test_S07_correction_in_other_utterance_warns() -> None:
    d = Draft(vitals=[temperature("36.8", ["u1"])])
    assert "値が複数" in warn_messages(d, CORRECTION)


def test_reordered_evidence_still_stops_old_value() -> None:
    d = Draft(vitals=[temperature("36.8", ["u3", "u1"])])
    assert "最新の値" in stop_messages(d, CORRECTION)


def test_latest_value_passes() -> None:
    assert stop_messages(Draft(vitals=[temperature("36.4", ["u3"])]), CORRECTION) == ""


@pytest.mark.parametrize("conv", [YESTERDAY_SAME, YESTERDAY_OTHER], ids=["同じ発言", "別の発言"])
def test_today_value_passes_despite_yesterday(conv: list[Utterance]) -> None:
    assert stop_messages(Draft(vitals=[temperature("36.8", ["u1"])]), conv) == ""


@pytest.mark.parametrize("conv", [YESTERDAY_SAME, YESTERDAY_OTHER], ids=["同じ発言", "別の発言"])
def test_yesterday_value_is_stopped(conv: list[Utterance]) -> None:
    assert stop_messages(Draft(vitals=[temperature("37.5", [conv[-1].id])]), conv) != ""


def _pain_draft(text: str, evidence: list[str]) -> Draft:
    return Draft.model_validate({"soap": {"S": [{"text": text, "evidence": evidence}]}})


def test_pain_4_of_10_passes() -> None:
    assert stop_messages(_pain_draft("痛みは4/10。", ["u1", "u3"]), PAIN) == ""


def test_pain_10_of_10_is_stopped() -> None:
    assert "数" in stop_messages(_pain_draft("現在の痛みは10/10。", ["u3"]), PAIN)


def test_pain_8_of_10_scale_is_stopped() -> None:
    assert "数" in stop_messages(_pain_draft("痛みは10段階中8。", ["u3"]), PAIN)


ENTAIL_DRAFT = Draft.model_validate(
    {
        "soap": {"S": [{"text": "痛みの訴え。", "evidence": ["u1"]}]},
        "requests": [
            {
                "text": "タオル",
                "cue": {"kind": "時間指定", "text": "昼食前", "evidence": ["u1"]},
                "evidence": ["u1"],
            }
        ],
        "doctor_questions": [{"text": "食事の開始時期", "evidence": ["u1"]}],
    }
)
TARGETS = entail_targets(ENTAIL_DRAFT)


def test_entail_covers_all_sentence_kinds() -> None:
    assert [t.path for t in TARGETS] == [
        "soap.S[0]",
        "requests[0]",
        "requests[0].cue",
        "doctor_questions[0]",
    ]


def test_A04_entail_no_verdicts_flags_all() -> None:
    assert len(entail_checks(TARGETS, Verdicts(items=[]))) == len(TARGETS)


def test_A04_C06_entail_failure_flags_all() -> None:
    checks = entail_checks(TARGETS, None)
    assert len(checks) == len(TARGETS)
    assert {c.code for c in checks} == {"entail_unclear"}


def test_A04_entail_partial_flags_missing_ones() -> None:
    partial = Verdicts(items=[Verdict(index=0, verdict="supported", reason="")])
    assert len(entail_checks(TARGETS, partial)) == len(TARGETS) - 1


def test_A04_entail_all_supported_flags_nothing() -> None:
    all_ok = Verdicts(
        items=[Verdict(index=i, verdict="supported", reason="") for i in range(len(TARGETS))]
    )
    assert entail_checks(TARGETS, all_ok) == []


@pytest.mark.parametrize(
    ("text", "want"),
    [("37度2分ですね", ["37.2"]), ("お熱は38度です", ["38"]), ("三十七度です", ["37"])],
)
def test_R01_temperature_integer_and_degree_minute(text: str, want: list[str]) -> None:
    """体温：「○度○分」・整数・漢数字の「三十七度」も拾う。"""
    from app.checks.vital_extract import extract_vitals

    assert extract_vitals(text).get("体温") == want
