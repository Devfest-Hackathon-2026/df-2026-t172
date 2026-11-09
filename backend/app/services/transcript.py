"""テキスト入力（文字起こし済みの会話）を発言の列にする。"""

import re

from app.models.draft import Speaker, Utterance

_PREFIX = re.compile(r"^\s*(看護師|患者)\s*[:：]\s*")
_SPEAKER_BY_PREFIX: dict[str, Speaker] = {"看護師": "nurse", "患者": "patient"}


def parse_transcript(transcript: str) -> list[Utterance]:
    """1行1発言の文字起こしを、番号つきの発言の列にする。

    行が「看護師:」「患者:」で始まれば話者をそれにし、なければ不明にする。
    テキスト入力には時刻がないので start・end は None。
    """
    utterances = []
    for line in transcript.splitlines():
        if not line.strip():
            continue
        m = _PREFIX.match(line)
        speaker: Speaker = _SPEAKER_BY_PREFIX[m[1]] if m else "unknown"
        text = line[m.end() :] if m else line.strip()
        utterances.append(
            Utterance(id=f"u{len(utterances) + 1}", speaker=speaker, text=text.strip())
        )
    return utterances
