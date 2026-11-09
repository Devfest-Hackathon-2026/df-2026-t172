"""二段目の確認：下書きの各文が、根拠の発言だけから言えるかを Gemini に別に判定させる。

コードの照合（verify.py）では、数を含まない推測（「脱水傾向あり」）や否定の取り違え
（「腫れてない」→「腫れあり」）を止められない。そこを別の呼び出しで見る。

**明示的に supported と判定された文だけを通す**。判定が返らない文、呼び出しの失敗は
すべて entail_unclear として目立たせる（黙って通さない）。
"""

import re
from dataclasses import dataclass

from app.checks.conversation import Conversation
from app.checks.numbers_ja import scales
from app.checks.sentence_checks import stop
from app.models.draft import Check, Draft
from app.models.gemini import Verdict, Verdicts

ENTAIL_PROMPT = """看護記録の下書きの各文について、添えた「根拠の発言」だけから、その文の内容が言えるかを判定する。
- supported: 根拠の発言だけからそのまま言える
- not_supported: 根拠の発言にない内容（推測・診断・言い換えによる意味の変化・否定の取り違え・薬の名前や量）を含む
- unclear: 判断できない
一般的な医学知識で補ってはいけない。根拠の発言に書かれていないことは not_supported にする。
根拠の発言には話者（看護師・患者）を付けてある。看護師がその場で観察・測定した内容を述べた発言は、
その観察・測定の根拠になる。看護師の発言だという理由だけで not_supported や unclear にしない。
「前の質問」は、答えの意味を知るための文脈としてだけ使う。すべての文に必ず1つずつ判定を返す。
reason は日本語で、40字以内で書く。"""

_SPEAKER_LABEL = {"nurse": "看護師", "patient": "患者"}
_QUESTION_END = re.compile(r"(?:か|かね|ですか|ますか)[。]?$|[?？]$")


@dataclass(frozen=True)
class EntailTarget:
    """二段目にかける1文。path は画面でのひも付けに使う。"""

    path: str
    text: str
    evidence: list[str]


def entail_targets(draft: Draft) -> list[EntailTarget]:
    """二段目にかける文を並べる（S・O・依頼・手がかり・医師への確認）。

    看護師が足した要素（added_by=nurse）はかけない（A-12。Gemini も呼ばない）。
    """
    out = [
        EntailTarget(f"soap.{part}[{i}]", s.text, s.evidence)
        for part in ("S", "O")
        for i, s in enumerate(getattr(draft.soap, part))
        if s.added_by == "ai"
    ]
    for i, req in enumerate(draft.requests):
        if req.added_by == "nurse":
            continue
        out.append(EntailTarget(f"requests[{i}]", req.text, req.evidence))
        if req.cue:
            out.append(
                EntailTarget(
                    f"requests[{i}].cue",
                    f"{req.cue.kind}: {req.cue.text}",
                    req.cue.evidence,
                )
            )
    out += [
        EntailTarget(f"doctor_questions[{i}]", q.text, q.evidence)
        for i, q in enumerate(draft.doctor_questions)
        if q.added_by == "ai"
    ]
    return out


def _context_question(evidence_id: str, conv: Conversation) -> str | None:
    """答えの意味を知るために添える、直前の看護師の質問（尺度の質問を含む）。"""
    question = conv.previous_nurse_text(evidence_id)
    if question is None or conv.speaker[evidence_id] == "nurse":
        return None
    if scales(question) or _QUESTION_END.search(question.strip()):
        return question
    return None


def build_entail_input(targets: list[EntailTarget], conv: Conversation) -> str:
    """判定させる文と、それぞれの根拠の発言（と前の質問）を並べる。"""
    lines = []
    for i, target in enumerate(targets):
        quoted = " / ".join(
            f"{e}[{_SPEAKER_LABEL.get(conv.speaker.get(e, ''), '不明')}]「{conv.text.get(e, '')}」"
            for e in target.evidence
        )
        lines.append(f"[{i}] 文: {target.text}\n    根拠: {quoted or '（根拠なし）'}")
        for e in target.evidence:
            question = _context_question(e, conv) if e in conv.text else None
            if question is not None:
                prev = conv.previous_id[e]
                lines.append(f"    前の質問: {prev}「{question}」")
    return "\n".join(lines)


def entail_outcomes(targets: list[EntailTarget], verdicts: Verdicts | None) -> list[Verdict]:
    """文ごとに判定を1つずつそろえる。判定が返らない文・呼び出しの失敗は unclear にする。

    Args:
        targets: 二段目にかけた文（`entail_targets` の結果）
        verdicts: 二段目の判定。呼び出しに失敗したときは None

    Returns:
        targets と同じ並びの判定（index は targets の番号）
    """
    got = {v.index: v for v in (verdicts.items if verdicts else [])}
    missing_reason = "確認の呼び出しが失敗した" if verdicts is None else "判定が返らなかった"
    return [
        got.get(i) or Verdict(index=i, verdict="unclear", reason=missing_reason)
        for i in range(len(targets))
    ]


def outcome_checks(targets: list[EntailTarget], outcomes: list[Verdict]) -> list[Check]:
    """supported でない判定を Check にする（targets と outcomes は同じ並び）。"""
    out = []
    for target, outcome in zip(targets, outcomes, strict=True):
        if outcome.verdict == "not_supported":
            message = f"二段目：根拠の発言だけからは言えない（{outcome.reason}）"
            out.append(stop(target.path, "entail_not_supported", message))
        elif outcome.verdict == "unclear":
            message = f"二段目：判断できない（{outcome.reason}）"
            out.append(stop(target.path, "entail_unclear", message))
    return out


def entail_checks(targets: list[EntailTarget], verdicts: Verdicts | None) -> list[Check]:
    """supported と明示的に判定されなかった文を Check にする（A-04）。"""
    return outcome_checks(targets, entail_outcomes(targets, verdicts))
