"""思わぬ例外を、いちばん外側で受け止める（決まり P-04・SEC-05）。純粋な ASGI。

Starlette は Exception のハンドラで 500 を返した後に、例外を投げ直す
（starlette/middleware/errors.py）。そのままだと uvicorn がスタックトレースと
例外の本文（会話の文が入ることがある）をログに出す。ここで受け止めて投げ直さない。
"""

from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from app.errors import INTERNAL_ERROR_MESSAGE, error_body
from app.services.safe_log import log_failure


class ErrorGuard:
    """包んだアプリから漏れた例外を、種類だけログに残して 500 の JSON にする。"""

    def __init__(self, app: ASGIApp, mode: str):
        """包むアプリと、エラーに入れるモードで作る。"""
        self.app, self.mode = app, mode

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        """包んだアプリを呼ぶ。例外は投げ直さない。"""
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        started = False

        async def watched_send(message: Message) -> None:
            nonlocal started
            if message["type"] == "http.response.start":
                started = True
            await send(message)

        try:
            await self.app(scope, receive, watched_send)
        except Exception as e:
            if started:
                return  # 内側のハンドラが 500 を返し、ログも残した後の投げ直し
            log_failure("unexpected_error", e)
            body = error_body(self.mode, "internal_error", INTERNAL_ERROR_MESSAGE)
            await JSONResponse(body, status_code=500)(scope, receive, send)
