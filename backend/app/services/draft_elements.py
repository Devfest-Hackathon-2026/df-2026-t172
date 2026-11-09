"""看護師が足せる要素（S・O の文・依頼・医師への確認・手で入力が必要なもの）を並べる。

看護師が足した印（A-12）と、AI の要素の指紋（draft_token）の両方が、同じ範囲を見るように
ここ1か所で決める。
"""

from app.models.draft import Draft, EvidencedText, PatientRequest, SoapSentence

Element = SoapSentence | PatientRequest | EvidencedText


def addable_elements(draft: Draft) -> list[tuple[str, Element]]:
    """看護師が足せる要素を、場所（例 `requests[1]`）つきで並べる。"""
    lists: tuple[tuple[str, list[Element]], ...] = (
        ("soap.S", list(draft.soap.S)),
        ("soap.O", list(draft.soap.O)),
        ("requests", list(draft.requests)),
        ("doctor_questions", list(draft.doctor_questions)),
        ("manual_needed", list(draft.manual_needed)),
    )
    return [(f"{name}[{i}]", e) for name, items in lists for i, e in enumerate(items)]
