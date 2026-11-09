"""日本語の会話から数を取り出す（Gemini を通さずコードで行う）。

漢数字は「数の文脈」に限って読み替える。「十分（じゅうぶん）」「もう一度」を
10 や 1 として拾い、脈拍や文中の数と取り違えないため（批判の記録 3回目の8）。
"""

import re
import unicodedata

_KANJI_DIGIT = {
    "〇": 0, "零": 0, "一": 1, "二": 2, "三": 3, "四": 4,
    "五": 5, "六": 6, "七": 7, "八": 8, "九": 9,
}  # fmt: skip
_KANJI_UNIT = {"十": 10, "百": 100, "千": 1000}

# 数ではない漢数字を含む言葉。読み替えの前に隠し、後で戻す
_NOT_NUMBER_WORDS = (
    "十分", "一緒", "一応", "一旦", "一番", "一杯", "一度", "一部", "一気",
    "一生", "一体", "一方", "一般", "一言", "一瞬", "一層", "一向", "一時的",
    "万一", "唯一", "統一", "同一", "七夕", "九州", "四国",
)  # fmt: skip
_HIDE_BASE = 0xE000  # 私用領域の文字で隠す（数字にならない）

_KANJI_RUN = re.compile(r"[〇零一二三四五六七八九十百千]+(?:点[〇零一二三四五六七八九]+)?")
# 1文字だけの漢数字は、後ろに単位・助数詞などが続くときだけ数とみなす
_NUMBER_FOLLOWER = re.compile(
    r"\s*(?:度|分|錠|単位|回|点|号|割|%|パーセント|ミリ|mg|cc|本|包|枚|個|"
    r"人|歳|時|日|年|くらい|ぐらい|位|です|の|で|/)"
)
_DEGREE_MINUTE = re.compile(r"(3[4-9]|4[0-2])度(\d)分")  # 体温の「36度8分」だけ
_MIDDLE_DOT = re.compile(r"(\d)[・･](\d)")
# 「SpO2」の 2 を数として拾わないよう、下付きの ₂ にしておく（\d に当たらない）
_SPO2_WORD = re.compile(r"(?i)sp\s*o\s*2")
_NUMBER = re.compile(r"\d+(?:\.\d+)?")


def _kanji_to_int(kanji: str) -> int:
    """千・百・十を含む漢数字（9999 まで）を整数にする。"""
    total, digits = 0, 0
    for ch in kanji:
        if ch in _KANJI_UNIT:
            total += (digits or 1) * _KANJI_UNIT[ch]
            digits = 0
        else:
            digits = digits * 10 + _KANJI_DIGIT[ch]
    return total + digits


def _convert_kanji_run(m: re.Match[str]) -> str:
    """「三十六点八」→「36.8」。数の文脈でなければそのまま返す。"""
    run = m.group()
    whole, _, fraction = run.partition("点")
    is_single_digit = len(whole) == 1 and whole in _KANJI_DIGIT and not fraction
    if is_single_digit and not _NUMBER_FOLLOWER.match(m.string, m.end()):
        return run
    out = str(_kanji_to_int(whole))
    if fraction:
        out += "." + "".join(str(_KANJI_DIGIT[c]) for c in fraction)
    return out


def _convert_kanji(text: str) -> str:
    """数でない言葉を隠してから、漢数字を読み替える。"""
    for i, word in enumerate(_NOT_NUMBER_WORDS):
        text = text.replace(word, chr(_HIDE_BASE + i))
    text = _KANJI_RUN.sub(_convert_kanji_run, text)
    for i, word in enumerate(_NOT_NUMBER_WORDS):
        text = text.replace(chr(_HIDE_BASE + i), word)
    return text


def normalize(text: str) -> str:
    """全角・漢数字・「36度8分」「36・8」を、比べやすい形に直す。"""
    text = unicodedata.normalize("NFKC", text)
    text = _SPO2_WORD.sub("SpO₂", text)
    text = _convert_kanji(text)
    text = _MIDDLE_DOT.sub(r"\1.\2", text)
    return _DEGREE_MINUTE.sub(r"\1.\2", text)


def ordered_numbers(text: str) -> list[str]:
    """文の中の数を、出てきた順に取り出す。"""
    return _NUMBER.findall(normalize(text))


def numbers(text: str) -> set[str]:
    """文の中の数の集合。"""
    return set(ordered_numbers(text))


_SCALE = re.compile(r"(\d+)段階")


def scales(text: str) -> set[str]:
    """「10段階で」のような尺度の数（痛みの 4/10 の「10」に当たる）。"""
    return set(_SCALE.findall(normalize(text)))


def strip_scale(text: str, allowed: set[str]) -> str:
    """文から「/10」「10段階中」の尺度の部分を取り除く（尺度の数は allowed に限る）。"""
    t = normalize(text)
    for n in allowed:
        t = re.sub(rf"/\s*{n}(?!\d)|{n}段階中?", "", t)
    return t
