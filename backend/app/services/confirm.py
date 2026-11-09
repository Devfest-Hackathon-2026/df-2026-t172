"""下書きを確定して、記録とタスクにする（POST /api/records、決まり A-01）。

確定を止める条件（409）:
- S-03：患者の照合が黄・赤で、看護師が「この患者で正しい」と確かめていない
- A-05：level=stop の Check のうち、残す／消すが決まっていないものがある

コードの照合はサーバーでやり直す（画面から届いた結果を信じて素通りさせない）。
二段目の結果は、署名で裏付けられたものと、呼び直した分を、ルートから受け取る
（`app.services.drafting.recheck_entail`）。

同じ confirm_id で2回送られたら（二重の確定）、同じ record_id・タスクの id で上書きする。
"""

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime

from app.checks.patient_match import match_patient
from app.checks.verify import verify
from app.errors import ApiError
from app.models.api import Patient, PatientMatch
from app.models.draft import Check, Draft
from app.models.record_request import RecordRequest
from app.services.chart import chart_text
from app.services.decisions import InvalidPathError, apply_decisions
from app.services.drafting import EntailRecheck
from app.services.nurse_added import nurse_added_paths
from app.services.record_documents import (
    kept_after_check,
    patient_check,
    record_document,
    task_documents,
)
from app.services.safe_log import log_event
from app.store.base import Document


@dataclass(frozen=True)
class Confirmed:
    """確定の結果。保存するのは record と tasks だけ。"""

    record_id: str
    chart_text: str
    record: Document
    tasks: list[Document]


def _ensure_patient_confirmed(req: RecordRequest, match: PatientMatch, patient: Patient) -> None:
    if match.level != "ok" and not req.patient_confirmed:
        raise ApiError(
            409,
            "patient_not_confirmed",
            f"{patient.room}号室 {patient.display_name}さんで正しいか確かめてから確定してください",
        )


def _stop_checks(req: RecordRequest, entail_checks: list[Check]) -> list[Check]:
    code_checks = verify(req.draft, req.utterances).checks
    return [c for c in code_checks + entail_checks if c.level == "stop"]


def _ensure_all_decided(req: RecordRequest, stop_checks: list[Check]) -> None:
    undecided = {c.path for c in stop_checks} - {d.path for d in req.decisions}
    if undecided:
        raise ApiError(
            409,
            "undecided_checks",
            f"引っかかった {len(undecided)} 件について、残すか消すかを選んでください",
        )


def _log_confirmed(
    record_id: str,
    req: RecordRequest,
    match: PatientMatch,
    final: Draft,
    stop_count: int,
    entail_rejudged: int,
    relabelled: int,
) -> None:
    """計測用の操作記録（設計 9章）。時刻・色・数だけを出す（P-04：会話の文・患者名は出さない）。

    ui_counts は画面でしか分からない数。入力の形で0以上の整数だけに限ってある。
    """
    actions = [d.action for d in req.decisions]
    log_event(
        "record_confirmed",
        record_id=record_id,
        timing=req.timing.model_dump(),
        patient_match=match.level,
        patient_confirmed=req.patient_confirmed,
        stopped=stop_count,
        kept=actions.count("keep"),
        deleted=actions.count("delete"),
        sentences={"S": len(final.soap.S), "O": len(final.soap.O)},
        requests=len(final.requests),
        entail_rejudged=entail_rejudged,
        nurse_added=len(nurse_added_paths(final)),
        relabelled_as_ai=relabelled,
        ui_counts=req.ui_counts.model_dump(),
        reported_by=req.reported_by,
    )


def confirm_record(
    req: RecordRequest,
    patient: Patient,
    roster: list[Patient],
    now: datetime,
    judge_entail: Callable[[], EntailRecheck],
    relabelled: int = 0,
) -> Confirmed:
    """確定してよいか確かめ、保存する記録とタスクを作る。

    judge_entail は、確定する下書き（消す前）に対する二段目の結果を返す。Gemini を
    呼び直すことがあるので、患者の確認（S-03）が済んでから呼ぶ。relabelled は、
    「看護師が足した」から AI の要素に戻した数（操作記録に出すだけ、A-12）。

    Raises:
        ApiError: 確定を止める条件に当たる場合（409）、場所の指定が誤っている場合（422）
    """
    match = match_patient(patient, roster, req.utterances)
    _ensure_patient_confirmed(req, match, patient)
    entail = judge_entail()
    stop_checks = _stop_checks(req, entail.checks)
    _ensure_all_decided(req, stop_checks)
    try:
        final, kept_paths = apply_decisions(req.draft, req.decisions)
    except InvalidPathError as e:
        raise ApiError(422, "invalid_decision", f"下書きにない場所が指されています（{e}）") from e

    record_id = f"r_{patient.id}_{req.confirm_id}"
    record = record_document(
        patient=patient,
        draft=final,
        utterances=req.utterances,
        decisions=req.decisions,
        kept=kept_after_check(kept_paths, stop_checks),
        patient_check_doc=patient_check(match, req.patient_confirmed),
        now=now,
        reported_by=req.reported_by,
    )
    _log_confirmed(record_id, req, match, final, len(stop_checks), entail.rejudged, relabelled)
    return Confirmed(
        record_id=record_id,
        chart_text=chart_text(patient, final, now),
        record=record,
        tasks=task_documents(patient, record_id, final, req.utterances, now),
    )
