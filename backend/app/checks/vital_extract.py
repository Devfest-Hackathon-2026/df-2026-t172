"""1つの発言から、項目ごとのバイタルの候補を取り出す（コードで行う）。

項目の言葉（体温・血圧・脈など）がある発言の数だけを候補にする。雑談の数
（「3年生」「13時」）を拾わないため。現場の言い方（サット・心拍数・
「上が132で下が78」）も拾う（批判の記録 3回目の8）。
"""

import re

from app.checks.numbers_ja import normalize

# 過去の値を言う文は、今の測定値の候補から外す（「昨日は37.5度でしたよ」）
PAST = re.compile(r"昨日は|昨夜は|前回|この前|先週|さっきは|朝は")

_TEMPERATURE_WORD = re.compile(r"体温|熱|度")
# 小数（36.8）か、「度」が続く整数（38度）。「37度2分」は normalize で 37.2 になる
_TEMPERATURE = re.compile(r"(?<![\d.])((?:3[4-9]|4[0-2])(?:\.\d(?![\d.])|(?=\s*度)))")
_BP_PAIR = re.compile(r"(?<![\d.])(\d{2,3})\s*(?:の|/)\s*(\d{2,3})(?![\d.])")
_BP_UPPER_LOWER = re.compile(
    r"上[はがも]?\s*(\d{2,3})\s*(?:で|、|,|の)?\s*下[はがも]?\s*(\d{2,3})(?!\d)"
)
_PULSE = re.compile(r"(?:脈拍|心拍数|心拍|脈)[はがもで]?\s*(\d{2,3})(?![\d.])")
_SPO2 = re.compile(
    r"(?:SpO₂|サチュレーション|サチュ|サット|酸素飽和度|酸素)[はがもで]?\s*(\d{2,3})(?![\d.])"
)
_RESPIRATION = re.compile(r"呼吸(?:数)?[はがもで]?\s*(\d{1,2})(?![\d.])")
# 血糖は「血糖」の後ろにある数のうち、時刻・年齢・量などの単位が付かないものだけ
_GLUCOSE = re.compile(
    r"(?<![\d./])(\d{2,3})(?![\d./])(?!\s*(?:時|分|年|歳|回|号|階|番|日|月|人|枚|"
    r"錠|単位|円|週|cm|kg|mg|ml|mL|%|度|か月|ヶ月))"
)
_GLUCOSE_RANGE = range(20, 601)


def _blood_pressure(text: str, context: str) -> list[str]:
    """血圧の候補（「132/78」の形）。「132の78」は血圧の言葉があるときだけ。"""
    found = [(m.start(), f"{m[1]}/{m[2]}") for m in _BP_UPPER_LOWER.finditer(text)]
    if "血圧" in text or "血圧" in context:
        found += [(m.start(), f"{m[1]}/{m[2]}") for m in _BP_PAIR.finditer(text)]
    return [value for _, value in sorted(found)]


def _glucose(text: str, context: str) -> list[str]:
    """血糖の候補。「血糖」より後ろにある数に限る。

    この発言に「血糖」がなく、直前の発言にあれば、この発言の数を頭から見る
    （「血糖測ってから着替えましょうか」「182ですね」。間が空くと別の発言になる。
    11/8 の音声の技術検証）。
    """
    start = text.find("血糖")
    if start < 0 and "血糖" in context:
        start = 0
    if start < 0:
        return []
    values = _GLUCOSE.findall(text, start)
    return [v for v in values if int(v) in _GLUCOSE_RANGE]


def extract_vitals(text: str, context: str = "") -> dict[str, list[str]]:
    """1つの発言から、項目ごとのバイタルの候補を出てきた順に取り出す。

    Args:
        text: 発言の文（過去の値を言う文は、呼び出し側で除いておく）
        context: 直前の発言の文。「お熱測りますね」「血圧測りますね」の次の発言で
            値だけが言われるときに、体温と血圧の言葉を探すのに使う

    Returns:
        項目 → 値の候補（血圧は「132/78」の形）
    """
    t, ctx = normalize(text), normalize(context)
    out: dict[str, list[str]] = {}
    # 「度」は読み替え（37度2分→37.2）で消えるので、読み替えの前の文で探す
    if _TEMPERATURE_WORD.search(text) or _TEMPERATURE_WORD.search(context):
        out["体温"] = _TEMPERATURE.findall(t)
    out["血圧"] = _blood_pressure(t, ctx)
    out["脈拍"] = _PULSE.findall(t)
    out["SpO2"] = _SPO2.findall(t)
    out["呼吸数"] = _RESPIRATION.findall(t)
    out["血糖"] = _glucose(t, ctx)
    return {item: values for item, values in out.items() if values}


def drop_past_sentences(text: str) -> str:
    """過去の値を言う文だけを除き、残りは1つの文としてつなげたまま返す。

    「血圧も測りますね。132の78」のように、項目の言葉と値が別の文にあるため、
    発言を丸ごとは捨てない。
    """
    sentences = re.split(r"[。！？!?]", text)
    return "。".join(s for s in sentences if not PAST.search(s))
