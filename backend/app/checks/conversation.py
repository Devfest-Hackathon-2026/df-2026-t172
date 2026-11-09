"""照合で何度も引く、発言の列の索引。"""

from dataclasses import dataclass
from itertools import pairwise

from app.models.draft import Speaker, Utterance


@dataclass(frozen=True)
class Conversation:
    """発言番号から、文・話者・直前の発言を引けるようにしたもの。"""

    utterances: list[Utterance]
    text: dict[str, str]
    speaker: dict[str, Speaker]
    previous_id: dict[str, str]

    @classmethod
    def of(cls, utterances: list[Utterance]) -> "Conversation":
        """発言の列から索引を作る。"""
        return cls(
            utterances=utterances,
            text={u.id: u.text for u in utterances},
            speaker={u.id: u.speaker for u in utterances},
            previous_id={b.id: a.id for a, b in pairwise(utterances)},
        )

    def previous_nurse_text(self, utterance_id: str) -> str | None:
        """直前の発言が看護師のものなら、その文を返す。"""
        prev = self.previous_id.get(utterance_id)
        if prev is None or self.speaker[prev] != "nurse":
            return None
        return self.text[prev]
