"""総合テスト（`scripts.smoke_test`）の結果の数え方と、API の呼び方。

合言葉はヘッダーに入れるだけで、出力・ログ・ファイルには出さない。
"""

from typing import Any

import httpx

# Gemini を呼ぶ下書きは時間がかかる（live で数十秒）。ほかは短くてよい
SLOW_TIMEOUT = 90.0
FAST_TIMEOUT = 20.0


class Smoke:
    """API を順に叩き、期待どおりかを1行ずつ「OK/NG」で出す。

    Attributes:
        ng: NG の数（最後に終了コードにする）
        mode: `/api/health` が返した mode（mock か live）。分かるまでは None
    """

    def __init__(self, base_url: str, passcode: str) -> None:
        """URL と合言葉を受け取る。合言葉は表示しない。"""
        self._client = httpx.Client(base_url=base_url.rstrip("/"), timeout=FAST_TIMEOUT)
        self._passcode = passcode
        self.ok_count = 0
        self.ng = 0
        self.skipped = 0
        self.mode: str | None = None

    def close(self) -> None:
        """接続を閉じる。"""
        self._client.close()

    # --- 結果の表示 ---

    def check(self, name: str, passed: bool, detail: str = "") -> bool:
        """1項目の結果を出して数える。通ったかを返す。"""
        if passed:
            self.ok_count += 1
        else:
            self.ng += 1
        mark = "OK" if passed else "NG"
        print(f"{mark}  {name}" + (f" — {detail}" if detail else ""))
        return passed

    def skip(self, name: str, reason: str) -> None:
        """飛ばした項目を出す（NG には数えない）。"""
        self.skipped += 1
        print(f"--  {name} — 飛ばした（{reason}）")

    def expect_status(self, name: str, response: httpx.Response | None, status: int) -> bool:
        """状態コードを確かめる。違えば状態コードとエラーの code だけを出す（本文は出さない）。"""
        if response is None:
            return self.check(name, False, "つながらなかった")
        if response.status_code == status:
            return self.check(name, True, f"{status}")
        return self.check(
            name, False, f"{status} のはずが {response.status_code}（{error_code(response)}）"
        )

    # --- API の呼び出し ---

    def request(
        self,
        method: str,
        path: str,
        *,
        passcode: bool = True,
        slow: bool = False,
        **kwargs: Any,
    ) -> httpx.Response | None:
        """API を呼ぶ。つながらなければ、理由（例外の種類だけ）を出して None を返す。"""
        headers = {"X-Passcode": self._passcode} if passcode else {}
        timeout = SLOW_TIMEOUT if slow else FAST_TIMEOUT
        try:
            return self._client.request(method, path, headers=headers, timeout=timeout, **kwargs)
        except httpx.HTTPError as e:
            print(f"    {method} {path} がつながらなかった（{type(e).__name__}）")
            return None


def error_code(response: httpx.Response) -> str:
    """エラーの応答から code だけを取り出す（形が違えば「code なし」）。"""
    try:
        return str(response.json()["error"]["code"])
    except (ValueError, KeyError, TypeError):
        return "code なし"
