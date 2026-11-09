"""下書きを作る流れ（設計 5章の処理の流れ）。

発言の列 → ① Gemini の下書き → SOAP の形 → 照合（コード）→ ② 二段目の確認。
選んだ患者は Gemini に渡さない（答えに写されるのを防ぐため）。
"""

from collections.abc import Callable
from dataclasses import dataclass
from typing import Literal

from app.checks.entail import (
    EntailTarget,
    entail_checks,
    entail_outcomes,
    entail_targets,
    outcome_checks,
)
from app.checks.patient_match import match_patient
from app.checks.verify import verify
from app.live.interfaces import GeminiClient
from app.models.api import DraftResponse, Mode, Patient
from app.models.draft import Check, Draft, EntailSeal, Utterance
from app.models.gemini import Verdicts
from app.services.entail_seal import EntailSealer
from app.services.safe_log import log_failure
from app.services.soap import to_soap


@dataclass(frozen=True)
class EntailRecheck:
    """確定のときの二段目の結果。rejudged は、確定のときに Gemini に呼び直した文の数。"""

    checks: list[Check]
    rejudged: int


@dataclass(frozen=True)
class Checked:
    """照合と二段目の結果。seals は二段目をかけたときだけ入る。"""

    checks: list[Check]
    missing: list[str]
    seals: list[EntailSeal]


def _judge(
    gemini: GeminiClient, targets: list[EntailTarget], utterances: list[Utterance]
) -> Verdicts | None:
    """二段目を呼ぶ。失敗の種類によらず None を返す（黙って通さず全文を止める、A-04・C-06）。"""
    try:
        return gemini.judge(targets, utterances)
    except Exception as e:
        log_failure("entail_failed", e)
        return None


def run_entail(
    draft: Draft, utterances: list[Utterance], gemini: GeminiClient, sealer: EntailSealer
) -> tuple[list[Check], list[EntailSeal]]:
    """二段目の確認をかけ、止める文と、判定の署名を返す。"""
    targets = entail_targets(draft)
    if not targets:
        return [], []
    outcomes = entail_outcomes(targets, _judge(gemini, targets, utterances))
    return outcome_checks(targets, outcomes), sealer.seal(targets, utterances, outcomes)


def check_draft(
    draft: Draft,
    utterances: list[Utterance],
    gemini: GeminiClient | None,
    sealer: EntailSealer,
) -> Checked:
    """コードの照合と、（gemini があれば）二段目の確認。"""
    result = verify(draft, utterances)
    if gemini is None:
        return Checked(result.checks, result.missing, [])
    entail, seals = run_entail(draft, utterances, gemini, sealer)
    return Checked(result.checks + entail, result.missing, seals)


def recheck_entail(
    draft: Draft,
    utterances: list[Utterance],
    seals: list[EntailSeal],
    sealer: EntailSealer,
    gemini_for_rest: Callable[[], GeminiClient | None],
) -> EntailRecheck:
    """確定のときの二段目の結果。署名で裏付けられない文だけ、二段目を呼び直す。

    Args:
        draft: 確定する下書き（消す前のもの）
        utterances: 発言の列
        seals: 画面が送り返した署名つきの判定
        sealer: 署名を確かめる部品
        gemini_for_rest: 呼び直しが要るときだけ呼ぶ。None を返したら（今日の上限など）
            呼び直さず、その文を「判断できない」で止める

    Returns:
        二段目で止める文と、呼び直した文の数（上限で呼ばなかった文は数えない）
    """
    targets = entail_targets(draft)
    trusted = sealer.trusted_outcomes(targets, utterances, seals)
    sealed = sorted(trusted)
    checks = outcome_checks([targets[i] for i in sealed], [trusted[i] for i in sealed])
    rest = [t for i, t in enumerate(targets) if i not in trusted]
    if not rest:
        return EntailRecheck(checks, rejudged=0)
    gemini = gemini_for_rest()
    verdicts = _judge(gemini, rest, utterances) if gemini is not None else None
    rejudged = len(rest) if gemini is not None else 0
    return EntailRecheck(checks + entail_checks(rest, verdicts), rejudged)


def build_draft(
    *,
    mode: Mode,
    patient: Patient,
    roster: list[Patient],
    utterances: list[Utterance],
    input_kind: Literal["audio", "text"],
    gemini: GeminiClient,
    sealer: EntailSealer,
) -> DraftResponse:
    """発言の列から、画面に返す下書き一式を作る（保存しない）。"""
    draft = to_soap(gemini.generate_draft(utterances))
    checked = check_draft(draft, utterances, gemini, sealer)
    return DraftResponse(
        mode=mode,
        patient=patient,
        patient_match=match_patient(patient, roster, utterances),
        input=input_kind,
        utterances=utterances,
        draft=draft,
        checks=checked.checks,
        missing=checked.missing,
        entail_seals=checked.seals,
    )
