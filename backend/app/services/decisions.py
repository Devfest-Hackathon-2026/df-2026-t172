"""看護師の「残す／消す」を下書きに当てる。"""

import re

from app.models.draft import Draft
from app.models.record_request import Decision

_PATH = re.compile(
    r"^(vitals|soap\.S|soap\.O|requests|manual_needed|doctor_questions)\[(\d+)\](\.cue)?$"
)


class InvalidPathError(ValueError):
    """下書きの中に、その場所がない。"""


def _target_list(draft: Draft, list_name: str) -> list:
    if list_name.startswith("soap."):
        return getattr(draft.soap, list_name.removeprefix("soap."))
    return getattr(draft, list_name)


def parse_path(path: str, draft: Draft) -> tuple[str, int, bool]:
    """「requests[1].cue」→ ("requests", 1, True)。下書きにない場所なら例外。

    Raises:
        InvalidPathError: 形が違うか、下書きにその場所がない場合
    """
    m = _PATH.match(path)
    if m is None or (m[3] and m[1] != "requests"):
        raise InvalidPathError(path)
    list_name, index = m[1], int(m[2])
    items = _target_list(draft, list_name)
    if index >= len(items) or (m[3] and items[index].cue is None):
        raise InvalidPathError(path)
    return list_name, index, bool(m[3])


def _renumber(removals: dict[str, set[int]], list_name: str, index: int) -> int | None:
    """消した要素を詰めた後の番号。その要素自体が消えたら None。"""
    removed = removals.get(list_name, set())
    if index in removed:
        return None
    return index - sum(1 for r in removed if r < index)


def apply_decisions(draft: Draft, decisions: list[Decision]) -> tuple[Draft, list[tuple[str, str]]]:
    """「消す」と決めた要素を除いた下書きと、「残す」と決めた要素の場所を返す。

    元の下書きは変えない。手がかりを消した依頼は、緊急度を none に戻す。
    同じ要素に「残す」と「消す」の両方があれば、消す。

    Returns:
        (確定する下書き, 残した要素の (元の場所, 消した分を詰めた後の場所) の並び)

    Raises:
        InvalidPathError: 下書きにない場所が指されている場合
    """
    result = draft.model_copy(deep=True)
    removals: dict[str, set[int]] = {}
    kept: list[tuple[str, str, int, bool]] = []
    for decision in decisions:
        list_name, index, is_cue = parse_path(decision.path, result)
        if decision.action == "keep":
            kept.append((decision.path, list_name, index, is_cue))
        elif is_cue:
            request = result.requests[index]
            request.cue, request.urgency = None, "none"
        else:
            removals.setdefault(list_name, set()).add(index)

    kept_paths: list[tuple[str, str]] = []
    for original, list_name, index, is_cue in kept:
        new_index = _renumber(removals, list_name, index)
        if new_index is None or (is_cue and result.requests[index].cue is None):
            continue
        kept_paths.append((original, f"{list_name}[{new_index}]" + (".cue" if is_cue else "")))

    for list_name, indexes in removals.items():
        items = _target_list(result, list_name)
        items[:] = [item for i, item in enumerate(items) if i not in indexes]
    return result, list(dict.fromkeys(kept_paths))
