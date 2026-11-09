"""ログに会話の文・患者名を出さないための書き方（決まり P-04）。

ログは Cloud Logging に JSON 1行で出す。例外の本文（`str(e)`）やスタックトレースは
出さない：Gemini の応答の検証エラーなどには、会話の文がそのまま入ることがあるため。
出すのは、何が起きたか（event）・例外の種類・数だけ。
"""

import json
import logging
from typing import Any

logger = logging.getLogger("app")


def log_event(event: str, severity: str = "INFO", **fields: Any) -> None:
    """時刻と数だけの操作記録を出す。fields に会話の文・患者名を入れない。"""
    entry = {"severity": severity, "event": event, **fields}
    logger.log(getattr(logging, severity, logging.INFO), json.dumps(entry, ensure_ascii=False))


def log_failure(event: str, error: BaseException) -> None:
    """失敗を、例外の種類だけで記録する（本文とスタックトレースは出さない）。"""
    log_event(event, severity="ERROR", error_type=type(error).__name__)
