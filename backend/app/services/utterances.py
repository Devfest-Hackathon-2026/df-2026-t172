"""文字起こしの単語の列を、番号つきの発言の列にする（番号はサーバーが振る）。

話者の割り当て（設計 5章）：最初に話した人を看護師、次に話した人を患者とする。
3人目以降と、話者分離が使えなかったときは「不明」にする（話者の照合から外れる）。
ただし、患者が先に話すと全部が逆になる（11/8 の技術検証）。そこで、部屋番号・敬称つきの
名前・バイタルの数を言った側を看護師らしいとみなし、患者の側のほうが看護師らしければ
入れ替える。それでも違うときは、画面で看護師が入れ替える（/api/verify に送り直す）。

文字起こしの記号の書き方は、照合（app/checks）が読める形に直す（11/8 の技術検証で
chirp_3 が「37.4°」「36.5°C」「118-70」と書いた。照合は「度」「/」「の」で読む）。
"""

import re
from dataclasses import dataclass

from app.checks.vital_extract import extract_vitals
from app.models.draft import Speaker, Utterance

# 同じ話者でも、これより長く間が空いたら別の発言にする（秒）
PAUSE_SPLIT_SECONDS = 1.5
_SENTENCE_END = ("。", "？", "?", "！", "!")

_DEGREE = re.compile(r"\s*(?:°\s*C|℃|°)")
# 「118-70」の形（2〜3桁の数どうし）だけを「118/70」にする。電話番号のような長い並びは触らない
_NUMBER_PAIR = re.compile(r"(?<![\d.\-])(\d{2,3})\s*[-‐−–ー]\s*(\d{2,3})(?![\d.\-])")


def normalize_transcript(text: str) -> str:
    """文字起こしの記号を、照合が読める形に直す（°・℃ → 度、118-70 → 118/70）。"""
    return _NUMBER_PAIR.sub(r"\1/\2", _DEGREE.sub("度", text))


# 看護師らしさの手がかり。部屋番号（「号」は聞き違いで落ちることがある）とバイタルは重く、
# 敬称つきの名前は軽く数える（患者も「隣の山本さん」と言うため）
_ROOM = re.compile(r"\d{3,4}\s*号?室")
_HONORIFIC = re.compile(r"(?<!お)([一-龥]{1,4}|[ァ-ヶー]{2,6})さー?ん")
_NOT_NAMES = {"孫", "娘", "息子", "奥", "旦那", "皆", "先生", "看護師", "患者"}
ROOM_POINTS, VITAL_POINTS, NAME_POINTS = 2, 2, 1


def nurse_score(text: str) -> int:
    """1つの発言の看護師らしさ（部屋番号・バイタルの数・敬称つきの名前）。"""
    score = ROOM_POINTS * bool(_ROOM.search(text))
    score += VITAL_POINTS * bool(extract_vitals(normalize_transcript(text)))
    names = [m for m in _HONORIFIC.findall(text) if m not in _NOT_NAMES]
    return score + NAME_POINTS * bool(names)


@dataclass(frozen=True)
class Word:
    """文字起こしの1語。speaker_label は話者分離のラベル（なければ空）。"""

    text: str
    start: float
    end: float
    speaker_label: str = ""


def _speaker_roles(words: list[Word]) -> dict[str, Speaker]:
    roles: dict[str, Speaker] = {}
    order: list[Speaker] = ["nurse", "patient"]
    for w in words:
        if w.speaker_label and w.speaker_label not in roles:
            roles[w.speaker_label] = order.pop(0) if order else "unknown"
    return roles


def _swap_if_patient_looks_like_nurse(
    roles: dict[str, Speaker], groups: list[list[Word]]
) -> dict[str, Speaker]:
    """患者とした側のほうが看護師らしければ、看護師と患者を入れ替える。"""
    scores: dict[str, int] = {}
    for group in groups:
        label = group[0].speaker_label
        scores[label] = scores.get(label, 0) + nurse_score("".join(w.text for w in group))
    nurse = next((k for k, v in roles.items() if v == "nurse"), None)
    patient = next((k for k, v in roles.items() if v == "patient"), None)
    if nurse is None or patient is None or scores.get(patient, 0) <= scores.get(nurse, 0):
        return roles
    return {**roles, nurse: "patient", patient: "nurse"}


def utterances_from_words(words: list[Word]) -> list[Utterance]:
    """話者が変わるか、間が空いたところで区切って発言にする。"""
    groups: list[list[Word]] = []
    for w in words:
        last = groups[-1][-1] if groups else None
        same_turn = (
            last is not None
            and last.speaker_label == w.speaker_label
            and w.start - last.end <= PAUSE_SPLIT_SECONDS
            # 話者が分からないときは、話者の代わりに文の終わりで区切る
            and not (not w.speaker_label and last.text.endswith(_SENTENCE_END))
        )
        if same_turn:
            groups[-1].append(w)
        else:
            groups.append([w])
    roles = _swap_if_patient_looks_like_nurse(_speaker_roles(words), groups)
    return [
        Utterance(
            id=f"u{i}",
            speaker=roles.get(group[0].speaker_label, "unknown"),
            start=round(group[0].start, 2),
            end=round(group[-1].end, 2),
            # 日本語は語の間に空白を入れない
            text=normalize_transcript("".join(w.text for w in group).strip()),
        )
        for i, group in enumerate(groups, 1)
    ]
