"""live の流れのテストで使う差し替え（Gemini・Speech-to-Text を実際には呼ばない）。"""

from app.checks.entail import EntailTarget
from app.live.interfaces import PreparedAudio
from app.live.mock_gemini import MockGemini
from app.models.draft import Utterance
from app.models.gemini import GeminiDraft, Verdicts
from app.services.audio_chunks import chunk_spans
from app.services.mock_data import load_scenarios
from tests.helpers import gemini_draft_of, utterances_of

S1_TRANSCRIPT = "\n".join(
    f"{'看護師' if u.speaker == 'nurse' else '患者'}: {u.text}" for u in utterances_of("s1")
)


class FakeGemini:
    """呼ばれた回数を数え、場面1の見本を返す。judge_error を入れると二段目が失敗する。"""

    def __init__(self, judge_error: Exception | None = None):
        self.calls: list[str] = []
        self._mock = MockGemini(list(load_scenarios()), draft_scenario_id="s1")
        self._judge_error = judge_error
        self.seen_utterances: list[Utterance] = []

    def generate_draft(self, utterances: list[Utterance]) -> GeminiDraft:
        self.calls.append("draft")
        self.seen_utterances = utterances
        return gemini_draft_of("s1")

    def judge(self, targets: list[EntailTarget], utterances: list[Utterance]) -> Verdicts:
        self.calls.append("judge")
        if self._judge_error:
            raise self._judge_error
        return self._mock.judge(targets, utterances)


class FakeSpeech:
    """音声を読んだことにして、場面1の発言の列を返す。seconds で読んだ長さを決められる。"""

    def __init__(self, seconds: float = 30.0) -> None:
        self.audio: bytes | None = None
        self.seconds = seconds
        self.transcribed = False

    def prepare(self, audio: bytes) -> PreparedAudio:
        self.audio = audio
        return PreparedAudio(pcm=audio, seconds=self.seconds, spans=chunk_spans(self.seconds))

    def transcribe(self, prepared: PreparedAudio) -> list[Utterance]:
        self.transcribed = True
        return utterances_of("s1")
