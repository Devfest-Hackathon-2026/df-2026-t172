"""二段目の判定への署名（決まり A-04・A-05 をサーバーで強制する）。

確定（`/api/records`）のとき、画面から届いた二段目の結果をそのまま信じると、
`checks: []` を送るだけで二段目で止まった文を確定できてしまう。そこで、
`/api/drafts`・`/api/verify` が返す判定に HMAC の署名を付け、確定のときに確かめる。

署名は「文・根拠の発言番号・根拠の発言の文・判定・理由」に結びつける。文や根拠を
直すと署名が合わなくなり、その文は確定のときに二段目を呼び直す。
"""

import hashlib
import hmac
import json

from app.checks.conversation import Conversation
from app.checks.entail import EntailTarget
from app.models.draft import EntailSeal, Utterance
from app.models.gemini import Verdict

MAX_REASON_CHARS = 100  # EntailSeal.reason の上限に合わせる


class EntailSealer:
    """判定に署名し、確定のときに確かめる。鍵は設定（ENTAIL_SEAL_KEY）から渡す。"""

    def __init__(self, key: bytes):
        """署名の鍵で作る。"""
        self._key = key

    def _sign(self, target: EntailTarget, conv: Conversation, verdict: str, reason: str) -> str:
        evidence_texts = [conv.text.get(e) for e in target.evidence]
        message = json.dumps(
            [target.text, target.evidence, evidence_texts, verdict, reason], ensure_ascii=False
        )
        return hmac.new(self._key, message.encode(), hashlib.sha256).hexdigest()

    def seal(
        self, targets: list[EntailTarget], utterances: list[Utterance], outcomes: list[Verdict]
    ) -> list[EntailSeal]:
        """文ごとの判定（targets と同じ並び）に署名を付ける。"""
        conv = Conversation.of(utterances)
        seals = []
        for target, outcome in zip(targets, outcomes, strict=True):
            reason = outcome.reason[:MAX_REASON_CHARS]
            sig = self._sign(target, conv, outcome.verdict, reason)
            seals.append(
                EntailSeal(path=target.path, verdict=outcome.verdict, reason=reason, sig=sig)
            )
        return seals

    def trusted_outcomes(
        self, targets: list[EntailTarget], utterances: list[Utterance], seals: list[EntailSeal]
    ) -> dict[int, Verdict]:
        """署名で裏付けられた判定を、targets の番号ごとに返す。

        同じ文に裏付けのある判定が2つあって食い違うときは、止める方を使う
        （二段目を何度も呼ばせて、通る判定だけを選ぶのを防ぐ）。
        """
        conv = Conversation.of(utterances)
        index_by_path = {t.path: i for i, t in enumerate(targets)}
        trusted: dict[int, Verdict] = {}
        for seal in seals:
            i = index_by_path.get(seal.path)
            if i is None or not self._valid(targets[i], conv, seal):
                continue
            if i not in trusted or trusted[i].verdict == "supported":
                trusted[i] = Verdict(index=i, verdict=seal.verdict, reason=seal.reason)
        return trusted

    def _valid(self, target: EntailTarget, conv: Conversation, seal: EntailSeal) -> bool:
        expected = self._sign(target, conv, seal.verdict, seal.reason)
        return hmac.compare_digest(seal.sig, expected)
