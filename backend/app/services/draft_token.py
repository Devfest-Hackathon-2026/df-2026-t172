"""AI が書いた要素の印（draft_token）。看護師が足したと偽るのを防ぐ（決まり A-12）。

`/api/drafts` が返す下書きの、AI が書いた要素の文から指紋（ハッシュ）を作り、
HMAC で署名して `draft_token` として返す。画面は確定のときにそのまま送り返す。
確定のとき、`added_by: "nurse"` なのに指紋が token にある要素は、AI の要素として扱う
（照合と二段目をかけ直す）。

- 指紋は文を比べやすい形（NFKC、空白と末尾の句読点を除く）にしてから作る
- token には文そのものは入れない（指紋だけ。画面に返す量も小さく済む）
- 文を直してから「看護師が足した」にしたものは見分けられない。直した文は看護師が
  確かめて確定する（A-01）ので、ここでは「下書きのまま」の偽りだけを防ぐ
"""

import base64
import hashlib
import hmac
import json
import re
import unicodedata

from app.models.draft import Draft
from app.services.draft_elements import addable_elements

_DIGEST_CHARS = 16
_IGNORED = re.compile(r"\s+|[。．.、,！!？?]+$")


def fingerprint(text: str) -> str:
    """文の指紋。空白・末尾の句読点・全角半角の違いは同じとみなす。"""
    normalized = _IGNORED.sub("", unicodedata.normalize("NFKC", text))
    return hashlib.sha256(normalized.encode()).hexdigest()[:_DIGEST_CHARS]


class DraftTokenSigner:
    """draft_token を作り、確かめる。鍵は二段目の署名と同じ設定から渡す。"""

    def __init__(self, key: bytes):
        """署名の鍵で作る（二段目の署名と取り違えないよう、用途の名前を混ぜる）。"""
        self._key = b"draft_token:" + key

    def _sign(self, payload: bytes) -> str:
        return hmac.new(self._key, payload, hashlib.sha256).hexdigest()

    def issue(self, draft: Draft) -> str:
        """AI が書いた下書きの、要素の指紋に署名した token を作る。"""
        digests = sorted({fingerprint(e.text) for _, e in addable_elements(draft)})
        payload = base64.urlsafe_b64encode(json.dumps(digests).encode())
        return f"{payload.decode()}.{self._sign(payload)}"

    def ai_fingerprints(self, token: str | None) -> set[str] | None:
        """署名の合う token なら AI の要素の指紋を返す。ない・合わないなら None。"""
        if not token or "." not in token:
            return None
        payload, sig = token.rsplit(".", 1)
        if not hmac.compare_digest(sig, self._sign(payload.encode())):
            return None
        try:
            digests = json.loads(base64.urlsafe_b64decode(payload))
        except ValueError:
            return None
        return {d for d in digests if isinstance(d, str)}
