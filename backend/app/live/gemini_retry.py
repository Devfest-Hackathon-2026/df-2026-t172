"""Gemini の呼び出しの再試行（1回だけ）と、失敗のログ。

再試行するのは、待てば通りそうな失敗だけ：
- 429（混んでいる・割り当ての上限）と 503（一時的に使えない）
- 返った JSON が決めた形に合わない（構造化出力でもまれに崩れる）

タイムアウトやそのほかの失敗は再試行しない（待ち時間が延びるだけのため）。
2回目も失敗したら例外をそのまま投げ、呼び出し側が 502 にする（モックには切り替えない、C-05）。
"""

import time
from collections.abc import Callable
from typing import TypeVar

from pydantic import ValidationError

from app.services.safe_log import log_event

T = TypeVar("T")

RETRY_STATUS = frozenset({429, 503})
RETRY_WAIT_SECONDS = 1.5


def status_of(error: BaseException) -> int | None:
    """API の状態コード（google.genai.errors.APIError の code）。なければ None。"""
    code = getattr(error, "code", None)
    return code if isinstance(code, int) else None


def is_retryable(error: BaseException) -> bool:
    """待ってもう1回呼べば通りそうな失敗か。"""
    return isinstance(error, ValidationError) or status_of(error) in RETRY_STATUS


def _attempt_logged(
    attempt: Callable[[], T], *, tries: int, purpose: str, model: str, retry_allowed: bool
) -> T:
    """1回呼ぶ。失敗したら、目的・モデル・秒・状態コード・例外の種類だけをログに出して投げ直す。

    例外の本文には会話の文が入ることがあるので出さない（P-04）。
    """
    started = time.perf_counter()
    try:
        return attempt()
    except Exception as e:
        will_retry = retry_allowed and is_retryable(e)
        log_event(
            "gemini_failed",
            severity="WARNING" if will_retry else "ERROR",
            purpose=purpose,
            model=model,
            seconds=round(time.perf_counter() - started, 2),
            status=status_of(e),
            error_type=type(e).__name__,
            attempt=tries,
            will_retry=will_retry,
        )
        raise


def call_with_retry(
    attempt: Callable[[], T],
    *,
    purpose: str,
    model: str,
    sleep: Callable[[float], None] = time.sleep,
) -> T:
    """attempt を呼び、再試行できる失敗なら少し待って1回だけ呼び直す。

    Raises:
        Exception: 再試行しない失敗のとき、または2回目も失敗したとき（attempt の例外のまま）
    """
    try:
        return _attempt_logged(attempt, tries=1, purpose=purpose, model=model, retry_allowed=True)
    except Exception as e:
        if not is_retryable(e):
            raise
    sleep(RETRY_WAIT_SECONDS)
    return _attempt_logged(attempt, tries=2, purpose=purpose, model=model, retry_allowed=False)
