"""照合の規則（docs/design/README.md 5章）。本番でもサーバー側で使う。

AI が付けた根拠を、コードで確かめる。ここで止められない誤り（否定の取り違え、
数を含まない推測の文）は、二段目の確認（`app.checks.entail`）で扱う。
"""

from dataclasses import dataclass

from app.checks.conversation import Conversation
from app.checks.sentence_checks import (
    evidence_checks,
    medication_checks,
    needs_patient_checks,
    number_checks,
    priority_checks,
    speaker_checks,
)
from app.checks.vital_checks import check_vitals
from app.models.draft import REQUIRED_VITALS, Check, Draft, PatientRequest, Utterance


@dataclass
class VerifyResult:
    """照合の結果。missing は照合に通ったバイタルから計算した抜け。"""

    checks: list[Check]
    missing: list[str]


def _sentence(
    path: str, body: str, evidence: list[str], conv: Conversation
) -> tuple[list[Check], bool]:
    """文に共通の照合（薬・根拠の番号・数）。2つめの値は根拠の番号が正しいか。"""
    found = medication_checks(path, body)
    bad_ids = evidence_checks(path, evidence, conv)
    if bad_ids:
        return found + bad_ids, False
    return found + number_checks(path, body, evidence, conv), True


def _request(i: int, req: PatientRequest, conv: Conversation) -> list[Check]:
    """依頼と、その手がかりの照合。"""
    path = f"requests[{i}]"
    found, ids_ok = _sentence(path, req.text, req.evidence, conv)
    if ids_ok:
        found += needs_patient_checks(path, req.evidence, conv, "依頼")
    if req.cue is None:
        return found
    cue_path = f"{path}.cue"
    cue_found, cue_ids_ok = _sentence(cue_path, req.cue.text, req.cue.evidence, conv)
    cue_found += priority_checks(cue_path, req.cue.text)
    # 「患者が急ぎと言った」の根拠は患者の発言に限る（批判の記録 3回目の4）
    if cue_ids_ok and req.cue.kind == "患者が急ぎと言った":
        cue_found += needs_patient_checks(
            cue_path, req.cue.evidence, conv, "「患者が急ぎと言った」"
        )
    return found + cue_found


def verify(draft: Draft, utterances: list[Utterance]) -> VerifyResult:
    """下書きの根拠を発言の列と照らし合わせる。

    Args:
        draft: 下書き（看護師が直した後のものでもよい）
        utterances: 発言の列。speaker が "unknown" の発言は話者の規則から外す

    Returns:
        引っかかったもの（場所つき）と、抜け
    """
    conv = Conversation.of(utterances)
    vitals = check_vitals(draft.vitals, conv)
    checks = list(vitals.checks)

    # 看護師が足した要素（added_by=nurse）は AI 向けの照合をかけない（A-12）。
    # 根拠の番号が実在するかは、入力のときに確かめてある（app.services.nurse_added）
    for part, expected, label in (("S", "patient", "S"), ("O", "nurse", "O")):
        for i, sentence in enumerate(getattr(draft.soap, part)):
            if sentence.added_by == "nurse":
                continue
            path = f"soap.{part}[{i}]"
            found, ids_ok = _sentence(path, sentence.text, sentence.evidence, conv)
            if ids_ok:
                found += speaker_checks(path, sentence.evidence, conv, expected, label)
            checks += found

    for i, req in enumerate(draft.requests):
        if req.added_by == "ai":
            checks += _request(i, req, conv)

    for i, question in enumerate(draft.doctor_questions):
        if question.added_by == "ai":
            path = f"doctor_questions[{i}]"
            checks += _sentence(path, question.text, question.evidence, conv)[0]

    # 手で入力が必要なものは、薬の話を書いてよい場所なので薬の語は見ない
    for i, manual in enumerate(draft.manual_needed):
        if manual.added_by == "ai":
            checks += evidence_checks(f"manual_needed[{i}]", manual.evidence, conv)

    missing = [item for item in REQUIRED_VITALS if item not in vitals.verified]
    return VerifyResult(checks=checks, missing=missing)
