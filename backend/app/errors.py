"""エラーの形をそろえる：`{"mode": ..., "error": {"code": ..., "message": ...}}`。

message は画面にそのまま出せる日本語にする。
"""

from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.services.safe_log import log_failure

INTERNAL_ERROR_MESSAGE = "サーバーでエラーが起きました。もう一度お試しください"


class ApiError(Exception):
    """API が返すエラー。"""

    def __init__(self, status: int, code: str, message: str):
        """HTTP の状態コード、機械向けの code、画面に出す日本語の message。"""
        super().__init__(message)
        self.status, self.code, self.message = status, code, message


class BodyTooLarge(HTTPException):
    """送られた本文が上限を超えた（413、SEC-04）。

    本文の読み込みの途中で投げるので、FastAPI が 400 に読み替えないよう
    HTTPException の子にしておく。
    """

    def __init__(self, code: str, message: str):
        """機械向けの code と、画面に出す日本語の message。"""
        super().__init__(status_code=413, detail=message)
        self.code, self.message = code, message


def error_body(mode: str, code: str, message: str) -> dict:
    """エラーの応答の本文。"""
    return {"mode": mode, "error": {"code": code, "message": message}}


def _body(request: Request, code: str, message: str) -> dict:
    return error_body(request.app.state.settings.mode, code, message)


def install_error_handlers(app: FastAPI) -> None:
    """ApiError・入力の形の誤り・存在しない URL を、同じ形で返すようにする。"""

    @app.exception_handler(ApiError)
    async def _api_error(request: Request, exc: ApiError) -> JSONResponse:
        return JSONResponse(_body(request, exc.code, exc.message), status_code=exc.status)

    @app.exception_handler(BodyTooLarge)
    async def _too_large(request: Request, exc: BodyTooLarge) -> JSONResponse:
        return JSONResponse(_body(request, exc.code, exc.message), status_code=413)

    @app.exception_handler(RequestValidationError)
    async def _invalid(request: Request, exc: RequestValidationError) -> JSONResponse:
        # 入力の値（会話の文かもしれない）は出さず、場所だけを出す
        where = ", ".join(".".join(str(p) for p in e["loc"]) for e in exc.errors()[:3])
        message = f"入力の形が正しくありません（{where}）"
        return JSONResponse(_body(request, "invalid_request", message), status_code=422)

    @app.exception_handler(Exception)
    async def _unexpected(request: Request, exc: Exception) -> JSONResponse:
        # SEC-05：内部の情報（スタックトレース・プロンプト）は応答に出さない。
        # P-04：ログにも例外の本文は出さず、種類だけを残す。Starlette はこの後に例外を
        # 投げ直すので、外側の ErrorGuard（app.middleware.error_guard）が受け止める
        log_failure("unexpected_error", exc)
        return JSONResponse(_body(request, "internal_error", INTERNAL_ERROR_MESSAGE), 500)

    @app.exception_handler(StarletteHTTPException)
    async def _http(request: Request, exc: StarletteHTTPException) -> JSONResponse:
        messages = {404: "見つかりません", 405: "この方法では呼べません"}
        message = messages.get(exc.status_code, "エラーが起きました")
        return JSONResponse(
            _body(request, f"http_{exc.status_code}", message), status_code=exc.status_code
        )
