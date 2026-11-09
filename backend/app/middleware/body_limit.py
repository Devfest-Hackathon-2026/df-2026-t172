"""送られる本文の大きさの上限（決まり SEC-04）。純粋な ASGI のミドルウェア。

- JSON などは `max_json_bytes`（既定 1MB）まで
- 音声（multipart）は `max_audio_bytes`（10MB）に、区切りの分の余裕を足した大きさまで

`Content-Length` があれば、本文を読む前に断る。なければ（chunked）読みながら数え、
超えたところで BodyTooLarge を投げる（app.errors のハンドラが 413 にする）。
"""

from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from app.errors import BodyTooLarge, error_body

# multipart の区切りと、患者の id などの欄の分
MULTIPART_OVERHEAD = 64 * 1024


class BodyLimit:
    """本文が上限を超えたら 413 を返す。"""

    def __init__(self, app: ASGIApp, *, mode: str, max_json_bytes: int, max_audio_bytes: int):
        """包むアプリ、エラーに入れるモード、JSON と音声の上限（バイト）で作る。"""
        self.app, self.mode = app, mode
        self.max_json_bytes, self.max_audio_bytes = max_json_bytes, max_audio_bytes

    def _error(self, is_audio: bool) -> BodyTooLarge:
        if is_audio:
            mb = self.max_audio_bytes // (1024 * 1024)
            return BodyTooLarge("audio_too_large", f"録音のファイルが大きすぎます（{mb}MB まで）")
        kb = self.max_json_bytes // 1024
        return BodyTooLarge("body_too_large", f"送るデータが大きすぎます（{kb:,}KB まで）")

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        """上限を確かめてから、包んだアプリに渡す。"""
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        headers = dict(scope["headers"])
        is_audio = headers.get(b"content-type", b"").startswith(b"multipart/form-data")
        limit = self.max_audio_bytes + MULTIPART_OVERHEAD if is_audio else self.max_json_bytes
        declared = headers.get(b"content-length", b"")
        if declared.isdigit() and int(declared) > limit:
            error = self._error(is_audio)
            body = error_body(self.mode, error.code, error.message)
            await JSONResponse(body, status_code=413)(scope, receive, send)
            return

        received = 0

        async def limited_receive() -> Message:
            nonlocal received
            message = await receive()
            if message["type"] == "http.request":
                received += len(message.get("body", b""))
                if received > limit:
                    raise self._error(is_audio)
            return message

        await self.app(scope, limited_receive, send)
