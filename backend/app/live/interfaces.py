"""外の有料サービス（Gemini・Speech-to-Text）の呼び口。

本物（Vertex AI・Speech-to-Text V2）と、テスト・モック用の差し替えが同じ形で
入れ替えられるように、ここで形だけを決める。
"""

from dataclasses import dataclass
from typing import Protocol

from app.checks.entail import EntailTarget
from app.models.draft import Utterance
from app.models.gemini import GeminiDraft, Verdicts


class GeminiClient(Protocol):
    """Gemini の2つの呼び出し（①下書き ②二段目の確認）。"""

    def generate_draft(self, utterances: list[Utterance]) -> GeminiDraft:
        """発言の列から下書きを作る。失敗したら例外を投げる。"""
        ...

    def judge(self, targets: list[EntailTarget], utterances: list[Utterance]) -> Verdicts:
        """各文が根拠の発言だけから言えるかを判定する。失敗したら例外を投げる。"""
        ...


@dataclass(frozen=True)
class PreparedAudio:
    """認識の前に読んだ音声（16kHz モノラルの PCM）と、その長さ・区切り。保存しない（P-01）。"""

    pcm: bytes
    seconds: float
    spans: list[tuple[float, float]]

    @property
    def calls(self) -> int:
        """認識を呼ぶ回数（区切りの数）。"""
        return len(self.spans)


class SpeechClient(Protocol):
    """音声の文字起こし（話者分離・時刻つき）。"""

    def prepare(self, audio: bytes) -> PreparedAudio:
        """音声を読み、長さと区切りを決める。読めなければ AudioUnreadable を投げる。"""
        ...

    def transcribe(self, prepared: PreparedAudio) -> list[Utterance]:
        """音声を発言の列にする。発言番号はサーバーが振る。失敗したら例外を投げる。"""
        ...
