"""設定（すべて環境変数から読む。合言葉や鍵はコードに書かない）。"""

import os
import secrets
from dataclasses import dataclass
from pathlib import Path

from app.models.api import Mode

BACKEND_DIR = Path(__file__).resolve().parent.parent
REPO_DIR = BACKEND_DIR.parent
MIN_PASSCODE_CHARS = 12


class ConfigError(RuntimeError):
    """起動に必要な設定がない・正しくない。"""


@dataclass(frozen=True)
class Settings:
    """アプリの設定。"""

    mode: Mode
    passcode: str
    project: str
    gemini_location: str
    gemini_model: str
    speech_location: str
    speech_model: str
    firestore_database: str
    daily_call_limit: int
    daily_call_limit_per_client: int
    max_json_bytes: int
    max_audio_bytes: int
    max_audio_seconds: float
    max_transcript_chars: int
    frontend_dir: Path
    seal_key: bytes


def _seal_key() -> bytes:
    """二段目の結果に付ける署名の鍵。なければ起動のたびに作る（最大1インスタンスのため）。"""
    given = os.environ.get("ENTAIL_SEAL_KEY", "")
    return given.encode() if given else secrets.token_bytes(32)


def load_settings() -> Settings:
    """環境変数から設定を読む。

    Raises:
        ConfigError: PASSCODE がない・12文字より短い、MODE が mock / live でない場合
    """
    mode = os.environ.get("MODE", "mock")
    if mode not in ("mock", "live"):
        raise ConfigError(f"MODE は mock か live にする（今は {mode!r}）")
    passcode = os.environ.get("PASSCODE", "")
    if len(passcode) < MIN_PASSCODE_CHARS:
        raise ConfigError(
            f"環境変数 PASSCODE（合言葉）を{MIN_PASSCODE_CHARS}文字以上で設定してから起動する"
        )
    return Settings(
        mode=mode,
        passcode=passcode,
        project=os.environ.get("GOOGLE_CLOUD_PROJECT", "df-2026-t172"),
        # gemini-3.5-flash は東京では従量課金で使えない（global・us・eu のみ）。P-05 の例外は未決
        gemini_location=os.environ.get("GEMINI_LOCATION", "global"),
        gemini_model=os.environ.get("GEMINI_MODEL", "gemini-3.5-flash"),
        # chirp_3 の日本語の話者分離は東京では断られる（11/8 の技術検証で 403）。P-05 の例外
        speech_location=os.environ.get("SPEECH_LOCATION", "us"),
        speech_model=os.environ.get("SPEECH_MODEL", "chirp_3"),
        firestore_database=os.environ.get("FIRESTORE_DATABASE", "(default)"),
        # 有料の呼び出し（Gemini・Speech-to-Text）の1日の上限（C-04 で 300回/日に決定）
        daily_call_limit=int(os.environ.get("DAILY_CALL_LIMIT", "300")),
        # 同じ接続元（IP）からの1日の上限。1人に全体の上限を使い切られないため
        daily_call_limit_per_client=int(os.environ.get("DAILY_CALL_LIMIT_PER_CLIENT", "30")),
        max_json_bytes=int(os.environ.get("MAX_JSON_BYTES", str(1024 * 1024))),
        # 入力の大きさの上限（SEC-04）：音声は3分・10MB、テキストは5,000文字
        max_audio_bytes=int(os.environ.get("MAX_AUDIO_BYTES", str(10 * 1024 * 1024))),
        max_audio_seconds=float(os.environ.get("MAX_AUDIO_SECONDS", "180")),
        max_transcript_chars=int(os.environ.get("MAX_TRANSCRIPT_CHARS", "5000")),
        frontend_dir=Path(os.environ.get("FRONTEND_DIR", REPO_DIR / "frontend")),
        seal_key=_seal_key(),
    )
