"""わざと壊した下書きで、どの層が誤りを止めるかを確かめる（spike/test_checks.py の30件）。

層:
    本番   … app.checks（verify・patient_match）が止める（本番でも働く）
    二段目 … コードでは止まらない。二段目の確認で扱う
    テスト … 期待値との比較でしか止まらない（本番では止まらない。設計に限界として書いた）
"""

from collections.abc import Callable
from typing import Any

import pytest

from app.checks.verify import verify
from tests.helpers import draft_of, utterances_of
from tests.scenario_eval import evaluate

Mutation = Callable[[dict[str, Any]], None]


def narrative(text: str, source: str, evidence: list[str]) -> Mutation:
    return lambda d: d["narrative"].append({"text": text, "source": source, "evidence": evidence})


def vital_value(i: int, value: str) -> Mutation:
    return lambda d: d["vitals"][i].update(value=value)


# (名前, 場面, 壊し方, 止まる場所, code, メッセージに含まれる語)
PRODUCTION_CASES = [
    ("体温の値を変える", "s1", vital_value(0, "37.9"), "vitals[0]", "value_mismatch", "根拠の値"),
    ("血圧の上下を逆に", "s1", vital_value(1, "78/132"), "vitals[1]", "value_mismatch", "根拠の値"),
    (
        "血圧の下を脈拍の値に",
        "s1",
        vital_value(1, "132/76"),
        "vitals[1]",
        "value_mismatch",
        "根拠の値",
    ),
    ("脈拍に血圧の下の値", "s1", vital_value(2, "78"), "vitals[2]", "value_mismatch", "根拠の値"),
    (
        "雑談の数を呼吸数に",
        "s1",
        lambda d: d["vitals"].append({"item": "呼吸数", "value": "3", "evidence": ["u6"]}),
        "vitals[3]",
        "value_mismatch",
        "この項目の今の値がない",
    ),
    (
        "言い直し前の体温を足す",
        "s5",
        lambda d: d["vitals"].insert(0, {"item": "体温", "value": "36.8", "evidence": ["u7"]}),
        "vitals[1]",
        "duplicate_item",
        "2つある",
    ),
    (
        "言い直し前の体温に変える",
        "s5",
        vital_value(0, "36.8"),
        "vitals[0]",
        "value_mismatch",
        "最新の値",
    ),
    (
        "根拠を全部並べる",
        "s1",
        lambda d: d["narrative"][0].update(evidence=[f"u{i}" for i in range(1, 19)]),
        "soap.S[0]",
        "no_evidence",  # SEC-04：上限（3件）を超えた根拠は空にして止める
        "根拠の発言がない",
    ),
    (
        "文中の数を変える",
        "s1",
        lambda d: d["narrative"][0].update(text="現在の痛みは7/10。"),
        "soap.S[0]",
        "number_not_in_evidence",
        "根拠の発言にない",
    ),
    (
        "訴えを看護師の観察に",
        "s1",
        lambda d: d["narrative"][0].update(source="nurse"),
        "soap.O[0]",
        "speaker_mismatch",
        "看護師以外",
    ),
    (
        "根拠のない推測",
        "s1",
        narrative("感染の疑い。", "nurse", []),
        "soap.O[1]",
        "no_evidence",
        "根拠",
    ),
    (
        "看護師の発言を依頼の根拠に",
        "s1",
        lambda d: d["requests"][0].update(evidence=["u16"]),
        "requests[0]",
        "speaker_mismatch",
        "患者の発言がない",
    ),
    (
        "依頼の数を変え、手がかりに至急",
        "s1",
        lambda d: d["requests"][0].update(
            text="タオルを3枚",
            cue={"kind": "患者が急ぎと言った", "text": "至急", "evidence": ["u15"]},
        ),
        "requests[0].cue",
        "priority_word",
        "優先度の語",
    ),
    (
        "薬の量を記述に",
        "s5",
        narrative("夕方に2錠内服予定。", "nurse", ["u10"]),
        "soap.O[0]",
        "medication",
        "薬",
    ),
]


@pytest.mark.parametrize("scenario_id", ["s1", "s2", "s4", "s5"])
def test_positive_scenarios_pass(scenario_id: str) -> None:
    assert evaluate(draft_of(scenario_id), scenario_id) == []


@pytest.mark.parametrize(
    ("name", "sid", "mutate", "path", "code", "word"),
    PRODUCTION_CASES,
    ids=[c[0] for c in PRODUCTION_CASES],
)
def test_S07_A03_A07_production_layer_stops(
    name: str, sid: str, mutate: Mutation, path: str, code: str, word: str
) -> None:
    checks = verify(draft_of(sid, mutate), utterances_of(sid)).checks
    hits = [c for c in checks if c.path == path and c.code == code]
    assert hits, f"{name}: {path} で {code} が出ない（出たもの: {checks}）"
    assert hits[0].level == "stop"
    assert word in hits[0].message


def test_A10_unevidenced_vital_does_not_hide_missing() -> None:
    mutate: Mutation = lambda d: d["vitals"].append({"item": "SpO2", "value": "98", "evidence": []})  # noqa: E731
    result = verify(draft_of("s1", mutate), utterances_of("s1"))
    assert any(c.path == "vitals[3]" and c.code == "no_evidence" for c in result.checks)
    assert "SpO2" in result.missing


@pytest.mark.parametrize(
    ("sid", "mutate"),
    [
        ("s5", narrative("脱水傾向あり。", "patient", ["u6"])),  # 数のない推測
        (
            "s1",
            narrative("夜間創部痛で3回覚醒した。", "patient", ["u6", "u9"]),
        ),  # 無関係な数を借りる
    ],
    ids=["数のない推測", "無関係な発言の数を借りる"],
)
def test_second_stage_layer_is_not_caught_by_code(sid: str, mutate: Mutation) -> None:
    """コードでは止まらない（二段目の確認で扱う）ことを確かめておく。"""
    checks = verify(draft_of(sid, mutate), utterances_of(sid)).checks
    assert [c for c in checks if c.level == "stop"] == []


@pytest.mark.parametrize(
    ("sid", "mutate", "word"),
    [
        ("s1", narrative("孫の見舞いあり。", "patient", ["u4"]), "雑談が記録に入った"),
        (
            "s1",
            lambda d: d["requests"].append(
                {"text": "テレビカードを買いたい", "cue": None, "evidence": ["u17"]}
            ),
            "依頼の数が違う",
        ),
        ("s5", lambda d: d.update(narrative=[]), "自由記述に拾われていない"),
    ],
    ids=["雑談を記録に", "答え終わった質問を依頼に", "埋もれた症状を落とす"],
)
def test_test_only_layer(sid: str, mutate: Mutation, word: str) -> None:
    """期待値との比較でしか止まらない（本番では全文表示で人が見る）。"""
    assert any(word in p for p in evaluate(draft_of(sid, mutate), sid))
