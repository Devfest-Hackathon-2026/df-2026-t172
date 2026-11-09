"""確定した下書きから、Firestore に入れる記録とタスクの1件を作る。

- P-01：音声は入れない
- P-02：会話の文の全体は入れない。確定した記録に残った要素の根拠になった発言だけを
  `evidence_utterances` に入れる（看護師が消した要素の根拠だけに使われた発言は入れない）
- P-03：`expires_at`（翌日0時）を付け、TTL で消す
- S-04・A-06：照合で止まったのに看護師が確認して進めたことを、記録のデータに残す
"""

from datetime import datetime

from app.models.api import Patient, PatientMatch
from app.models.draft import Check, Draft, PatientRequest, Utterance
from app.models.limits import MAX_PATIENT_WORDS, MAX_SAVED_CHARS
from app.models.record_request import Decision
from app.services.clock import expires_at
from app.services.soap import urgency_of
from app.store.base import Document

KEPT_NOTE = "看護師が確認して残した"
PATIENT_MISMATCH_NOTE = "照合で食い違いあり→看護師が確認"
PATIENT_UNVERIFIED_NOTE = "照合できず→看護師が確認"
# 記録に残す根拠の発言の上限（SEC-04。Firestore の1件は 1MiB まで）
MAX_SAVED_UTTERANCES = 100


def evidence_ids(draft: Draft) -> set[str]:
    """確定する下書きの全要素の根拠の発言番号（手入力のバイタルは根拠を持たない）。"""
    lists = [
        *(v.evidence for v in draft.vitals if v.source == "conversation"),
        *(s.evidence for s in draft.soap.S + draft.soap.O),
        *(r.evidence for r in draft.requests),
        *(r.cue.evidence for r in draft.requests if r.cue),
        *(m.evidence for m in draft.manual_needed + draft.doctor_questions),
    ]
    return {e for ev in lists for e in ev}


def evidence_utterances(draft: Draft, utterances: list[Utterance]) -> list[Document]:
    """根拠になった発言だけを、発言の順に（番号・話者・文。時刻と音声は残さない）。

    件数は MAX_SAVED_UTTERANCES まで、文は MAX_SAVED_CHARS 文字までで切る。
    """
    used = evidence_ids(draft)
    return [
        {"id": u.id, "speaker": u.speaker, "text": u.text[:MAX_SAVED_CHARS]}
        for u in utterances
        if u.id in used
    ][:MAX_SAVED_UTTERANCES]


def kept_after_check(kept_paths: list[tuple[str, str]], stop_checks: list[Check]) -> list[Document]:
    """止まったのに「残す」を選んだ要素の印（A-06）。カルテ用の文には出さない。"""
    codes_by_path: dict[str, list[str]] = {}
    for check in stop_checks:
        codes_by_path.setdefault(check.path, []).append(check.code)
    return [
        {"path": new_path, "codes": codes_by_path[original], "note": KEPT_NOTE}
        for original, new_path in kept_paths
        if original in codes_by_path
    ]


def patient_check(match: PatientMatch, confirmed: bool) -> Document:
    """患者の照合の結果と、看護師が確かめたか（S-04：赤でも理由の入力は要らない）。"""
    notes = {"stop": PATIENT_MISMATCH_NOTE, "confirm": PATIENT_UNVERIFIED_NOTE}
    return {
        "level": match.level,
        "confirmed_by_nurse": confirmed,
        "note": notes.get(match.level) if confirmed else None,
    }


def record_document(
    *,
    patient: Patient,
    draft: Draft,
    utterances: list[Utterance],
    decisions: list[Decision],
    kept: list[Document],
    patient_check_doc: Document,
    now: datetime,
    reported_by: str | None = None,
) -> Document:
    """Firestore の records の1件。reported_by は確定した看護師の自己申告（S-08）。"""
    return {
        "patient_id": patient.id,
        "room": patient.room,
        "name": patient.name,
        "full_name": patient.display_name,
        **draft.model_dump(
            include={"vitals", "soap", "requests", "manual_needed", "doctor_questions"}
        ),
        "evidence_utterances": evidence_utterances(draft, utterances),
        "decisions": [d.model_dump() for d in decisions],
        "kept_after_check": kept,
        "patient_check": patient_check_doc,
        "confirmed_reported_by": reported_by,
        "created_at": now,
        "expires_at": expires_at(now),
    }


def _urgency_set_by(req: PatientRequest) -> str:
    """看護師が足した依頼、または段を変えた依頼は nurse（A-08・A-12）。"""
    if req.added_by == "nurse" or req.urgency != urgency_of(req.cue):
        return "nurse"
    return "rule"


def patient_words(req: PatientRequest, utterances: list[Utterance]) -> list[str]:
    """依頼（と手がかり）の根拠のうち、患者か話者不明の発言の文を、発言の順に。

    AI がまとめた依頼の文とは別に、患者が実際に言ったことを看護師が見られるようにする。
    根拠になった発言だけなので、保存してよい範囲（P-02）に収まる。
    """
    used = set(req.evidence) | set(req.cue.evidence if req.cue else [])
    words = [
        u.text[:MAX_SAVED_CHARS]
        for u in utterances
        if u.id in used and u.speaker in ("patient", "unknown")
    ]
    return words[:MAX_PATIENT_WORDS]


def task_documents(
    patient: Patient,
    record_id: str,
    draft: Draft,
    utterances: list[Utterance],
    now: datetime,
) -> list[Document]:
    """依頼からタスクを作る。看護師が段を変えていれば urgency_set_by を nurse にする（A-08）。

    id は記録の id と依頼の順番から決める（二重の確定で同じタスクが2つできないように）。
    """
    return [
        {
            "id": f"t_{record_id.removeprefix('r_')}_{i}",
            "patient_id": patient.id,
            "room": patient.room,
            "name": patient.name,
            "full_name": patient.display_name,
            "record_id": record_id,
            "text": req.text,
            "patient_words": patient_words(req, utterances),
            "urgency": req.urgency,
            "urgency_set_by": _urgency_set_by(req),
            "category": req.category,
            "role": req.role,
            # 確定の画面で看護師が変えたかは分からないので、AI の依頼は ai として残す
            "category_set_by": "nurse" if req.added_by == "nurse" else "ai",
            "role_set_by": "nurse" if req.added_by == "nurse" else "ai",
            "cue": {"kind": req.cue.kind, "text": req.cue.text} if req.cue else None,
            "status": "open",
            "assigned_to": patient.assigned_to,  # 患者の受け持ちを写す（S-08）
            "assigned_set_by": "rule",
            "created_at": now,
            "done_at": None,
            "expires_at": expires_at(now),
        }
        for i, req in enumerate(draft.requests)
    ]
