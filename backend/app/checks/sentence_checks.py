"""文（S・O・依頼・手がかり・医師への確認）に当てる照合の部品。

どの部品も、引っかかった分の Check を返す。何も返さなければ通った。
"""

import re

from app.checks.conversation import Conversation
from app.checks.numbers_ja import normalize, numbers, scales, strip_scale
from app.models.draft import Check, CheckCode

MAX_EVIDENCE = 3

# 薬の語。語の一覧では完全には拾えない（二段目の確認でも見る）。
# 読み替えた後の文に当てるので「二錠」も「2錠」として拾う（批判の記録 3回目の6）
_MEDICATION = re.compile(
    r"薬|内服|頓服|服薬|服用|投与|投薬|処方|インスリン|点滴|注射|皮下注|静注|筋注|"
    r"輸液|湿布|座薬|坐薬|軟膏|点眼|吸入|貼付|痛み止め|鎮痛|解熱剤|睡眠導入|"
    r"眠剤|下剤|抗生|抗菌|ステロイド|ロキソニン|ロキソプロフェン|カロナール|"
    r"アセトアミノフェン|ボルタレン|セレコックス|トラマール|マグミット|"
    r"ワーファリン|ワルファリン|ヘパリン|ラシックス|"
    r"\d+(?:\.\d+)?\s*(?:錠|単位|mg|ミリ|mL|ml|cc|包|カプセル|本|滴|アンプル|μg|mcg)"
)
_PRIORITY = re.compile(r"至急|優先|最優先|緊急|急いで対応|すぐ対応")


def stop(path: str, code: CheckCode, message: str) -> Check:
    """確定を止める Check を作る。"""
    return Check(path=path, level="stop", code=code, message=message)


def evidence_checks(path: str, evidence: list[str], conv: Conversation) -> list[Check]:
    """根拠の番号が1〜3件で、すべて実在するか。"""
    if not evidence:
        return [stop(path, "no_evidence", "根拠の発言がない")]
    if len(evidence) > MAX_EVIDENCE:
        return [stop(path, "too_many_evidence", f"根拠が多すぎる（{len(evidence)}件）")]
    unknown = [e for e in evidence if e not in conv.text]
    if unknown:
        return [stop(path, "unknown_evidence", f"存在しない発言番号 {unknown}")]
    return []


def number_checks(path: str, body: str, evidence: list[str], conv: Conversation) -> list[Check]:
    """文の中の数が、すべて根拠の発言にあるか。

    借りてよいのは、根拠の直前が看護師の質問で「10段階で」のような尺度の数だけ。
    しかも「/10」「10段階中」の形でだけ使える（「10/10」の上の 10 は借りられない）。
    """
    scale_numbers: set[str] = set()
    for e in evidence:
        question = conv.previous_nurse_text(e)
        if question is not None:
            scale_numbers |= scales(question)
    in_evidence: set[str] = set().union(*(numbers(conv.text[e]) for e in evidence))
    not_found = numbers(strip_scale(body, scale_numbers)) - in_evidence
    if not not_found:
        return []
    return [
        stop(
            path,
            "number_not_in_evidence",
            f"数 {sorted(not_found)} が根拠の発言にない",
        )
    ]


def speaker_checks(
    path: str, evidence: list[str], conv: Conversation, expected: str, label: str
) -> list[Check]:
    """根拠の発言の話者が、文の種類に合うか（話者が不明な発言は外して見る）。

    Args:
        path: 下書きの中の場所
        evidence: 根拠の発言番号（実在するもの）
        conv: 発言の列
        expected: 根拠に要る話者（"patient" か "nurse"）
        label: メッセージに出す、文の種類の名前
    """
    known = [conv.speaker[e] for e in evidence if conv.speaker[e] != "unknown"]
    if all(s == expected for s in known):
        return []
    who = "患者" if expected == "patient" else "看護師"
    return [stop(path, "speaker_mismatch", f"{label}の根拠に{who}以外の発言がある")]


def needs_patient_checks(
    path: str, evidence: list[str], conv: Conversation, label: str
) -> list[Check]:
    """根拠に患者の発言（か話者が不明な発言）が少なくとも1つあるか。"""
    if any(conv.speaker[e] in ("patient", "unknown") for e in evidence):
        return []
    return [stop(path, "speaker_mismatch", f"{label}の根拠に患者の発言がない")]


def medication_checks(path: str, body: str) -> list[Check]:
    """薬の名前・量がないか。あれば「手で入力が必要」へ回させる。"""
    if not _MEDICATION.search(normalize(body)):
        return []
    return [stop(path, "medication", "薬の名前・量がある → 手で入力が必要へ移す")]


def priority_checks(path: str, body: str) -> list[Check]:
    """手がかりに、優先度の語（至急・優先など）がないか。"""
    if not _PRIORITY.search(body):
        return []
    return [stop(path, "priority_word", f"手がかりに優先度の語がある（{body}）")]
