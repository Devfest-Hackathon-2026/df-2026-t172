"""看護計画まわり：S・O の文に付けた plan_id の確かめと、看護計画ごとのまとめ。

- A-14：看護計画を付けるのは看護師だけ。下書きの印はすべて消して返す
- R-03：確定のとき、選んだ患者の看護計画にない plan_id は 422
- R-01：カルテ用の文を看護計画ごとにまとめる（並べ方だけ。行の形は app.services.chart）
- P-04：ログに出すのは数だけ（看護計画の id・label、送られた plan_id は出さない）
"""

import re
from dataclasses import dataclass
from typing import Any

from app.errors import ApiError
from app.models.care_plan import CarePlan
from app.models.draft import Draft, Soap, SoapSentence
from app.services.safe_log import log_event

UNPLANNED_HEADING = "計画外"
# message に並べる場所の数（それより多ければ「ほか n 件」）
_MAX_PLACES = 5
_PATH = re.compile(r"^soap\.([SO])\[(\d+)\]$")


@dataclass(frozen=True)
class PlanSection:
    """カルテ用の文の1つの欄。heading は看護計画の label か「計画外」。S・O は元の並び。"""

    heading: str
    S: list[SoapSentence]
    O: list[SoapSentence]  # noqa: E741


def clear_plan_ids(draft: Draft) -> Draft:
    """S・O のすべての文の plan_id を None にした写しを返す（A-14）。元の下書きは変えない。"""
    soap = draft.soap.model_copy(
        update={
            "S": [s.model_copy(update={"plan_id": None}) for s in draft.soap.S],
            "O": [s.model_copy(update={"plan_id": None}) for s in draft.soap.O],
        }
    )
    return draft.model_copy(update={"soap": soap})


def unknown_plan_paths(draft: Draft, care_plans: list[CarePlan]) -> list[str]:
    """選んだ患者の看護計画にない plan_id を持つ S・O の文の場所（例 `soap.S[1]`）。

    看護師が足した文、消すと決めた文を含む、すべての文を見る（決定8）。
    id は大文字と小文字も区別して、完全に同じものだけを一致とみなす。
    """
    known = {p.id for p in care_plans}
    return [
        f"soap.{part}[{i}]"
        for part in ("S", "O")
        for i, s in enumerate(getattr(draft.soap, part))
        if s.plan_id is not None and s.plan_id not in known
    ]


def sentence_label(path: str) -> str:
    """文の場所を、確認画面の表示と同じ書き方にする（`soap.S[1]` → `S 2文目`）。"""
    found = _PATH.match(path)
    if found is None:
        return path
    return f"{found.group(1)} {int(found.group(2)) + 1}文目"


def ensure_known_care_plans(draft: Draft, care_plans: list[CarePlan]) -> None:
    """選んだ患者の看護計画にない plan_id があれば、ログに数を出して止める（R-03）。

    confirm_record の先頭で呼ぶ（患者の確認と二段目より前、決定8）。message には
    当たった文の場所（「S 2文目」）を入れ、看護計画の label と送られた値は入れない。

    Raises:
        ApiError: 1件以上ある場合（422、code は unknown_care_plan）
    """
    paths = unknown_plan_paths(draft, care_plans)
    if not paths:
        return
    log_event(
        "record_rejected",
        severity="WARNING",
        code="unknown_care_plan",
        unknown_plan_sentences=len(paths),
    )
    places = "、".join(sentence_label(p) for p in paths[:_MAX_PLACES])
    if len(paths) > _MAX_PLACES:
        places += f" ほか{len(paths) - _MAX_PLACES}件"
    raise ApiError(
        422,
        "unknown_care_plan",
        f"この患者さんの看護計画にない計画が付いた文があります（{places}）。"
        "看護計画を選び直してください",
    )


def plan_sections(soap: Soap, care_plans: list[CarePlan]) -> list[PlanSection]:
    """カルテ用の文の欄を、看護計画の並び → 計画外の順に返す（R-01 の書き換え）。

    前後の空白を除いて空の文は、ないものとして扱う。どの文にも plan_id がなければ
    空の並びを返す（今の形で出す合図）。care_plans にない plan_id の文は計画外に入れる。
    文が1つもない欄は返さない。
    """
    s_list = [s for s in soap.S if s.text.strip()]
    o_list = [s for s in soap.O if s.text.strip()]
    if all(s.plan_id is None for s in s_list + o_list):
        return []
    known = {p.id for p in care_plans}

    def key(s: SoapSentence) -> str | None:
        return s.plan_id if s.plan_id in known else None

    sections = []
    for plan in care_plans:
        s_part = [s for s in s_list if key(s) == plan.id]
        o_part = [s for s in o_list if key(s) == plan.id]
        if s_part or o_part:
            sections.append(PlanSection(plan.label, s_part, o_part))
    s_rest = [s for s in s_list if key(s) is None]
    o_rest = [s for s in o_list if key(s) is None]
    if s_rest or o_rest:
        sections.append(PlanSection(UNPLANNED_HEADING, s_rest, o_rest))
    return sections


def plan_log_fields(draft: Draft, care_plans: list[CarePlan]) -> dict[str, Any]:
    """確定のログに足す数（要件9の1・9の2）。draft は消した文を除いた、確定する下書き。

    看護計画の id・label と、送られた plan_id の値は出さない（P-04）。
    """
    known = {p.id for p in care_plans}

    def counts(sentences: list[SoapSentence]) -> tuple[int, int]:
        planned = sum(1 for s in sentences if s.plan_id in known)
        return planned, len(sentences) - planned

    s_planned, s_unplanned = counts(draft.soap.S)
    o_planned, o_unplanned = counts(draft.soap.O)
    used = {s.plan_id for s in draft.soap.S + draft.soap.O if s.plan_id in known and s.text.strip()}
    return {
        "plan_sentences": {"S": s_planned, "O": o_planned},
        "unplanned_sentences": {"S": s_unplanned, "O": o_unplanned},
        "plans_used": len(used),
        "plans_available": len(care_plans),
    }
