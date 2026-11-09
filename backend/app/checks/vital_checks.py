"""バイタルの照合（設計 5章の照合の規則）。"""

from dataclasses import dataclass, field

from app.checks.conversation import Conversation
from app.checks.numbers_ja import ordered_numbers
from app.checks.sentence_checks import evidence_checks, stop
from app.checks.vital_extract import drop_past_sentences, extract_vitals
from app.models.draft import Check, Vital


@dataclass
class VitalResult:
    """バイタルの照合の結果。verified は照合に通った項目（抜けの計算に使う）。"""

    checks: list[Check] = field(default_factory=list)
    verified: set[str] = field(default_factory=set)


def current_values(conv: Conversation) -> dict[str, list[tuple[str, str]]]:
    """会話全体から、項目ごとの今の値の候補を (発言番号, 値) で発言の順に集める。

    発言の順・発言の中の順に並ぶので、各項目の最後の要素が最新の値。
    """
    found: dict[str, list[tuple[str, str]]] = {}
    previous_text = ""
    for u in conv.utterances:
        now = drop_past_sentences(u.text)
        for item, values in extract_vitals(now, context=previous_text).items():
            found.setdefault(item, []).extend((u.id, v) for v in values)
        previous_text = u.text
    return found


def _manual_value_ok(vital: Vital) -> bool:
    """手入力の値が数として読めるか（血圧は上と下の2つ）。"""
    want = 2 if vital.item == "血圧" else 1
    return len(ordered_numbers(vital.value)) == want


def _conversation_vital(path: str, vital: Vital, candidates: list[tuple[str, str]]) -> Check | None:
    """会話から拾ったバイタルの値が、根拠の発言の最新の値か。通れば None。"""
    in_evidence = [value for uid, value in candidates if uid in vital.evidence]
    want = ordered_numbers(vital.value)
    if not in_evidence:
        return stop(path, "value_mismatch", "根拠の発言にこの項目の今の値がない")
    if all(ordered_numbers(value) != want for value in in_evidence):
        return stop(
            path,
            "value_mismatch",
            f"値 {vital.value} が根拠の値 {in_evidence} にない",
        )
    latest = candidates[-1][1]
    if ordered_numbers(latest) != want:
        return stop(path, "value_mismatch", f"値 {vital.value} は最新の値 {latest} ではない")
    return None


def check_vitals(vitals: list[Vital], conv: Conversation) -> VitalResult:
    """バイタルを会話と照らし合わせる。

    手入力（source=manual）の値は会話と照合しない（根拠は看護師の手入力）。
    同じ項目が2つあれば、手入力かどうかに関係なく止める。
    """
    result = VitalResult()
    current = current_values(conv)
    seen: set[str] = set()
    for i, vital in enumerate(vitals):
        path = f"vitals[{i}]"
        if vital.item in seen:
            result.checks.append(stop(path, "duplicate_item", f"{vital.item}が2つある"))
            continue
        seen.add(vital.item)
        if vital.source == "manual":
            if _manual_value_ok(vital):
                result.verified.add(vital.item)
            continue
        problems = evidence_checks(path, vital.evidence, conv)
        candidates = current.get(vital.item, [])
        if not problems:
            mismatch = _conversation_vital(path, vital, candidates)
            problems = [mismatch] if mismatch else []
        result.checks += problems
        if not problems:
            result.verified.add(vital.item)
        distinct = list(dict.fromkeys(value for _, value in candidates))
        if len(distinct) > 1:
            result.checks.append(
                Check(
                    path=path,
                    level="warn",
                    code="multiple_values",
                    message=f"会話に値が複数ある（{' → '.join(distinct)}）。看護師が選ぶ",
                )
            )
    return result
