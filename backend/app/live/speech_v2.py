"""Speech-to-Text V2 の呼び出し（話者分離・語ごとの時刻つき）。

11/8 の技術検証（backend/scripts/run_live_speech.py）で分かったこと:
- chirp_3 の日本語の話者分離は asia-northeast1 では断られる（403）。us で使う（P-05 の例外）
- 同期の認識（recognize）は1回60秒まで。長い録音は区切って続ける（app.services.audio_chunks）
- m4a（AAC）をそのまま送ると、エラーなしで結果が空になる。FLAC に直して送る（app.live.audio_flac）
- 話者分離の結果が返らないときは、話者を「不明」として返す（照合から外れる）

音声はサーバーに保存しない（P-01）。読むときの一時ファイルは、読み終わったらすぐ消す。
"""

import math
import time
from concurrent.futures import ThreadPoolExecutor
from typing import Any

from app.live.audio_flac import decode_pcm, flac_of, pcm_seconds, pcm_slice
from app.live.interfaces import PreparedAudio
from app.models.draft import Utterance
from app.services.audio_chunks import Piece, chunk_spans, stitch
from app.services.safe_log import log_event
from app.services.utterances import Word, utterances_from_words

# 区切りは並べて認識する（3分で4つ。順にすると待ち時間が4倍になる）
_PARALLEL = 4

# モデルごとの単価（1分あたりのドル）。Speech-to-Text V2 の公式の料金ページで 2026-11-08 に確認：
# Recognition の Standard（chirp を含む）は月50万分まで $0.016/分。話者分離の追加料金はない。
# 1回の認識ごとに1秒単位で切り上げて課金される。地域による違いは料金ページにない
SPEECH_PRICES_PER_MINUTE: dict[str, float] = {"chirp_3": 0.016}
BILLING_INCREMENT_SECONDS = 1


def billed_seconds(seconds: float) -> int:
    """1回の認識で課金される秒数（1秒単位で切り上げ）。"""
    return math.ceil(seconds / BILLING_INCREMENT_SECONDS) * BILLING_INCREMENT_SECONDS


def _maybe_billed(error: BaseException) -> bool:
    """失敗した呼び出しが課金されうるか。入力・権限の誤り（4xx）は処理の前に断られる。

    11/8 の検証では 403（地域）と 400（60秒超）が返った。それ以外（時間切れ・5xx など）は、
    処理が進んだ後かもしれないので、見込みの額には数える。
    """
    # google.api_core の例外は code に HTTP の状態コード（400・403 など）を持つ
    status = getattr(error, "code", None)
    return not (isinstance(status, int) and 400 <= status < 500)


class GoogleSpeech:
    """Speech-to-Text V2。client はテストで差し替えられる。"""

    def __init__(
        self,
        project: str,
        location: str,
        model: str,
        client: Any = None,
        diarization: bool = True,
    ):
        """client を渡さなければ、最初の呼び出しのときに本物を作る。

        diarization=False は検証用（話者分離が結果を空にしていないかを切り分ける）。
        """
        self._project, self._location, self._model = project, location, model
        self._client = client
        self._diarization = diarization

    def _speech_client(self) -> Any:
        if self._client is None:
            from google.api_core.client_options import ClientOptions
            from google.cloud.speech_v2 import SpeechClient

            endpoint = f"{self._location}-speech.googleapis.com"
            self._client = SpeechClient(client_options=ClientOptions(api_endpoint=endpoint))
        return self._client

    def _request(self, audio: bytes) -> Any:
        from google.cloud.speech_v2.types import cloud_speech

        features = cloud_speech.RecognitionFeatures(
            enable_word_time_offsets=True,
            enable_automatic_punctuation=True,
            diarization_config=(
                cloud_speech.SpeakerDiarizationConfig(min_speaker_count=2, max_speaker_count=3)
                if self._diarization
                else None
            ),
        )
        config = cloud_speech.RecognitionConfig(
            auto_decoding_config=cloud_speech.AutoDetectDecodingConfig(),
            language_codes=["ja-JP"],
            model=self._model,
            features=features,
        )
        recognizer = f"projects/{self._project}/locations/{self._location}/recognizers/_"
        return cloud_speech.RecognizeRequest(recognizer=recognizer, config=config, content=audio)

    def recognize(self, audio: bytes) -> Any:
        """認識の結果をそのまま返す（検証スクリプトが、語の列にする前の形を見るため）。"""
        return self._speech_client().recognize(request=self._request(audio), timeout=120)

    def prepare(self, audio: bytes) -> PreparedAudio:
        """音声を読み、長さと区切りを決める（認識はまだ呼ばない。費用はかからない）。

        Raises:
            AudioUnreadable: 音声として読めなかった場合
        """
        pcm = decode_pcm(audio)
        seconds = pcm_seconds(pcm)
        return PreparedAudio(pcm=pcm, seconds=seconds, spans=chunk_spans(seconds))

    def recognize_pieces(self, prepared: PreparedAudio) -> list[Piece]:
        """区切りごとに FLAC にして認識する（区切りは並べて呼ぶ）。費用をログに出す。

        Raises:
            Exception: どれかの区切りの認識が失敗した場合（費用のログは出してから投げる）
        """

        def one(span: tuple[float, float]) -> Piece | BaseException:
            start, end = span
            try:
                response = self.recognize(flac_of(pcm_slice(prepared.pcm, start, end)))
            except Exception as e:
                return e
            # 区切りの長さより後に始まる語は捨てる（11/8 の検証で、録音の終わりの後に
            # 「あ」「はい」が出た。録音にない語を発言にしない）
            words = [w for w in words_of(response) if w.start <= end - start]
            return Piece(start=start, end=end, words=words)

        started = time.perf_counter()
        with ThreadPoolExecutor(max_workers=_PARALLEL) as pool:
            results = list(pool.map(one, prepared.spans))
        self._log_usage(prepared, results, time.perf_counter() - started)
        for result in results:
            if isinstance(result, BaseException):
                raise result
        return [r for r in results if isinstance(r, Piece)]

    def _log_usage(
        self, prepared: PreparedAudio, results: list[Piece | BaseException], seconds: float
    ) -> None:
        """区切りの数・送った秒数・課金の秒数・見込みの額を出す（会話の文は出さない、P-04）。"""
        sent = [end - start for start, end in prepared.spans]
        billable = [
            length
            for length, result in zip(sent, results, strict=True)
            if not isinstance(result, BaseException) or _maybe_billed(result)
        ]
        billed = sum(billed_seconds(length) for length in billable)
        price = SPEECH_PRICES_PER_MINUTE.get(self._model)
        failed = [type(r).__name__ for r in results if isinstance(r, BaseException)]
        warning = (
            {
                "message": f"単価を確かめていないモデル: {self._model}（SPEECH_PRICES_PER_MINUTE に足す）"
            }
            if price is None
            else {}
        )
        log_event(
            "speech_usage",
            severity="WARNING" if price is None or failed else "INFO",
            model=self._model,
            location=self._location,
            pieces=len(prepared.spans),
            audio_seconds=round(prepared.seconds, 2),
            sent_seconds=round(sum(sent), 2),
            billed_seconds=billed,
            usd=None if price is None else round(billed / 60 * price, 6),
            failed_pieces=len(failed),
            error_types=failed,
            seconds=round(seconds, 2),
            **warning,
        )

    def transcribe(self, prepared: PreparedAudio) -> list[Utterance]:
        """音声を発言の列にする（区切りをつなぎ、話者を通しで対応づける）。"""
        return utterances_from_words(stitch(self.recognize_pieces(prepared)))


def words_of(response: Any) -> list[Word]:
    """認識結果から、語の列（時刻・話者ラベルつき）を取り出す。

    語ごとの時刻が返らない結果は、結果の文全体を1語として扱う（話者は不明）。
    """
    words: list[Word] = []
    result_start = 0.0
    for result in response.results:
        if not result.alternatives:
            continue
        best = result.alternatives[0]
        result_end = result.result_end_offset.total_seconds()
        if best.words:
            words += [
                Word(
                    text=w.word,
                    start=w.start_offset.total_seconds(),
                    end=w.end_offset.total_seconds(),
                    speaker_label=w.speaker_label,
                )
                for w in best.words
            ]
        elif best.transcript.strip():
            words.append(Word(text=best.transcript, start=result_start, end=result_end))
        result_start = result_end
    return words
