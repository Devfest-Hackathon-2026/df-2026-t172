"""Gemini の下書きを、画面に渡す SOAP の形に直す。緊急度もここでコードが決める。"""

from app.models.draft import (
    Cue,
    Draft,
    EvidencedText,
    PatientRequest,
    Soap,
    SoapSentence,
    Urgency,
    Vital,
)
from app.models.gemini import GeminiCue, GeminiDraft, GeminiEvidencedText
from app.models.limits import MAX_EVIDENCE, MAX_ID_CHARS

_URGENCY_BY_CUE_KIND: dict[str, Urgency] = {
    "患者が急ぎと言った": "said_urgent",
    "時間指定": "timed",
}


def urgency_of(cue: Cue | GeminiCue | None) -> Urgency:
    """手がかりの種類から緊急度を決める（AI には決めさせない）。"""
    if cue is None:
        return "none"
    return _URGENCY_BY_CUE_KIND[cue.kind]


def draft_evidence(ids: list[str]) -> list[str]:
    """Gemini が付けた根拠を、下書きの上限（SEC-04）に収める。

    上限を超える根拠（4件以上・長すぎる番号）は空にして、照合で「根拠なし」として
    止める。切り詰めて通すと、根拠のない文が黙って通るおそれがあるため。
    """
    unique = list(dict.fromkeys(ids))
    if len(unique) > MAX_EVIDENCE or any(len(e) > MAX_ID_CHARS for e in unique):
        return []
    return unique


def _evidenced(item: GeminiEvidencedText) -> EvidencedText:
    return EvidencedText(text=item.text, evidence=draft_evidence(item.evidence))


def to_soap(gemini_draft: GeminiDraft) -> Draft:
    """話者が患者の文を S に、看護師の文を O に振り分ける。A と P は空で渡す。"""
    soap = Soap()
    for sentence in gemini_draft.narrative:
        part = soap.S if sentence.source == "patient" else soap.O
        part.append(SoapSentence(text=sentence.text, evidence=draft_evidence(sentence.evidence)))
    requests = [
        PatientRequest(
            text=r.text,
            urgency=urgency_of(r.cue),
            cue=Cue(kind=r.cue.kind, text=r.cue.text, evidence=draft_evidence(r.cue.evidence))
            if r.cue
            else None,
            evidence=draft_evidence(r.evidence),
            category=r.category,
            role=r.role,
        )
        for r in gemini_draft.requests
    ]
    return Draft(
        vitals=[
            Vital(item=v.item, value=v.value, evidence=draft_evidence(v.evidence))
            for v in gemini_draft.vitals
        ],
        soap=soap,
        requests=requests,
        manual_needed=[_evidenced(m) for m in gemini_draft.manual_needed],
        doctor_questions=[_evidenced(q) for q in gemini_draft.doctor_questions],
    )
