"""誰が操作しているかの確認（決まり SEC-01）。認証はこの1か所だけで行う。

最小版は合言葉（ヘッダー X-Passcode）だけを確かめ、看護師は区別しない。
11/9 に管理者のログイン・受け持ちの割り振りを足すときは、ここで Operator に
看護師の id と権限を入れる（S-08）。
"""

import hmac
from dataclasses import dataclass

from fastapi import Header, Request

from app.errors import ApiError


@dataclass(frozen=True)
class Operator:
    """操作している人。最小版では誰か分からないので nurse_id は None。"""

    nurse_id: str | None = None


def authenticate(request: Request, x_passcode: str | None = Header(default=None)) -> Operator:
    """合言葉を確かめ、操作している人を返す。

    Raises:
        ApiError: ヘッダーがない、または合言葉が違う場合（401）
    """
    expected = request.app.state.settings.passcode
    given = (x_passcode or "").encode()
    if not hmac.compare_digest(given, expected.encode()):
        raise ApiError(401, "bad_passcode", "合言葉が違います")
    return Operator()
