"""利用シーンの合否の観点（docs/design/scenarios.md）を機械的に確かめる。

注意：ここには「期待する出力との比較」が入っている。本番には期待値がないので、
本番で誤りを止めるのは照合（app.checks）と二段目の確認だけ。テストでは、負例ごとに
本番の照合で止まるかを別に確かめる（test_layers.py）。
"""

from typing import Any

from app.checks.numbers_ja import ordered_numbers
from app.checks.patient_match import match_patient
from app.checks.verify import verify
from app.models.draft import Draft
from tests.helpers import ROSTER, SCENARIOS, utterances_of


def _record_text(draft: Draft) -> str:
    """記録・依頼・医師への確認の全部の文（薬を書いてよい「手で入力が必要」は除く）。"""
    parts = [s.text for s in draft.soap.S + draft.soap.O]
    parts += [r.text + (r.cue.text if r.cue else "") for r in draft.requests]
    parts += [q.text for q in draft.doctor_questions]
    return " ".join(parts)


def evaluate(draft: Draft, scenario_id: str) -> list[str]:
    """期待する出力と比べ、合わない点を返す。空なら合格。"""
    scenario: dict[str, Any] = SCENARIOS[scenario_id]
    exp = scenario["expect"]
    utterances = utterances_of(scenario_id)
    problems: list[str] = []

    selected = next(p for p in ROSTER if p.id == scenario["patient_id"])
    match = match_patient(selected, ROSTER, utterances)
    got_match = {"room": match.room, "name": match.name, "others": match.others}
    if got_match != exp["patient"]:
        problems.append(f"患者の照合が違う: {got_match}（期待 {exp['patient']}）")

    got = {v.item: ordered_numbers(v.value) for v in draft.vitals}
    for item, value in exp["vitals"].items():
        if got.get(item) != ordered_numbers(value):
            problems.append(f"バイタルが違う: {item}={got.get(item)}（期待 {value}）")
    problems += [f"期待していないバイタルが出た: {i}" for i in got.keys() - exp["vitals"].keys()]

    result = verify(draft, utterances)
    if sorted(result.missing) != sorted(exp["missing"]):
        problems.append(f"抜けが違う: {result.missing}（期待 {exp['missing']}）")

    requests = " ".join(r.text for r in draft.requests)
    problems += [f"依頼に出ていない: {kw}" for kw in exp["request_keywords"] if kw not in requests]
    if len(draft.requests) != exp["request_count"]:
        problems.append(f"依頼の数が違う: {len(draft.requests)}件（期待 {exp['request_count']}件）")
    cues = " ".join(r.cue.text for r in draft.requests if r.cue)
    if exp.get("cue_any") and not any(c in cues for c in exp["cue_any"]):
        problems.append(f"手がかりが出ていない（{exp['cue_any']} のどれか）")

    narrative = " ".join(s.text for s in draft.soap.S + draft.soap.O)
    problems += [
        f"自由記述に拾われていない: {kw}"
        for kw in exp.get("narrative_keywords", [])
        if kw not in narrative
    ]
    manual = " ".join(m.text for m in draft.manual_needed)
    problems += [
        f"手で入力が必要に出ていない: {kw}"
        for kw in exp.get("manual_keywords", [])
        if kw not in manual
    ]
    record = _record_text(draft)
    problems += [f"判断・推測・薬の語が出た: {w}" for w in exp["forbidden"] if w in record]
    problems += [
        f"雑談が記録に入った: {w}" for w in exp["chat_keywords"] if w in record or w in manual
    ]
    problems += [f"照合: {c.path} {c.message}" for c in result.checks if c.level == "stop"]
    return problems
