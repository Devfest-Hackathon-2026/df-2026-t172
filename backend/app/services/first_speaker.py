"""画面が録音の前に選んだ「最初に話す人」で、発言の列の話者を合わせる。

話者は Gemini に下書きを作らせる前に正しくしておく必要がある。Gemini は話者を見て
S（患者）と O（看護師）に振り分け、依頼も患者の発言から拾うので、確認画面で後から
入れ替えても下書きの中身は直らない（`/api/verify` はコードの照合だけをやり直す）。

- 音声：最初に話した人（看護師か患者に決まった最初の発言）が指定と逆なら、
  看護師と患者を全部入れ替える。不明（unknown）の発言はそのまま
- テキスト：行の頭の「看護師:」「患者:」があればそれに従い、指定は使わない。
  どの行にもなければ、指定した人から交互に話したとみなす
- auto（既定）は何もしない（音声は最初の話者と内容から推定した割り当てのまま）
"""

from app.models.draft import FirstSpeaker, Speaker, Utterance

_OTHER: dict[Speaker, Speaker] = {"nurse": "patient", "patient": "nurse", "unknown": "unknown"}


def _swap_roles(utterances: list[Utterance]) -> list[Utterance]:
    return [u.model_copy(update={"speaker": _OTHER[u.speaker]}) for u in utterances]


def apply_to_audio(utterances: list[Utterance], first: FirstSpeaker) -> list[Utterance]:
    """音声から作った発言の列を、指定した最初の話者に合わせる。"""
    if first == "auto":
        return utterances
    known = next((u.speaker for u in utterances if u.speaker != "unknown"), None)
    if known is None or known == first:
        return utterances
    return _swap_roles(utterances)


def apply_to_text(utterances: list[Utterance], first: FirstSpeaker) -> list[Utterance]:
    """テキストの発言の列で、話者の書いていない会話を指定した人から交互に割り当てる。"""
    if first == "auto" or any(u.speaker != "unknown" for u in utterances):
        return utterances
    order: tuple[Speaker, Speaker] = (first, _OTHER[first])
    return [u.model_copy(update={"speaker": order[i % 2]}) for i, u in enumerate(utterances)]
