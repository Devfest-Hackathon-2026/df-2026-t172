"""看護師が足した要素（added_by=nurse）の扱い（決まり A-12）。

- AI 向けの照合と二段目はかけない（`app.checks.verify`・`app.checks.entail` が飛ばす）
- 根拠は任意。付けたなら、その発言番号が実在するかだけを確かめる（ない番号は 422）
- 下書きにあった文なのに nurse になっている要素は、AI の要素に戻す（偽りを防ぐ）
"""

from app.errors import ApiError
from app.models.draft import Draft, PatientRequest, Utterance
from app.services.draft_elements import Element, addable_elements
from app.services.draft_token import fingerprint


def _evidence_of(element: Element) -> list[str]:
    cue = element.cue if isinstance(element, PatientRequest) else None
    return element.evidence + (cue.evidence if cue else [])


def nurse_added_paths(draft: Draft) -> list[str]:
    """看護師が足した要素の場所。"""
    return [path for path, e in addable_elements(draft) if e.added_by == "nurse"]


def ensure_nurse_evidence_exists(draft: Draft, utterances: list[Utterance]) -> None:
    """看護師が足した要素の根拠の番号が、発言の列にあるか確かめる。

    Raises:
        ApiError: ない番号を指している場合（422）
    """
    known = {u.id for u in utterances}
    for path, element in addable_elements(draft):
        if element.added_by != "nurse":
            continue
        unknown = [e for e in _evidence_of(element) if e not in known]
        if unknown:
            raise ApiError(
                422, "unknown_evidence", f"{path} の根拠に、会話にない発言番号があります"
            )


def relabel_ai_elements(draft: Draft, ai_fingerprints: set[str] | None) -> tuple[Draft, int]:
    """nurse になっているのに AI の下書きにあった要素を、ai に戻した下書きを返す。

    Args:
        draft: 画面から届いた下書き
        ai_fingerprints: draft_token の指紋。token がない・署名が合わないときは None で、
            そのときは nurse の要素をすべて AI の要素として扱う（照合を逃さない側に倒す）

    Returns:
        (戻した後の下書き, ai に戻した要素の数)
    """
    result = draft.model_copy(deep=True)
    relabelled = 0
    for _, element in addable_elements(result):
        if element.added_by != "nurse":
            continue
        if ai_fingerprints is None or fingerprint(element.text) in ai_fingerprints:
            element.added_by = "ai"
            relabelled += 1
    return result, relabelled
