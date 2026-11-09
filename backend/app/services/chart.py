"""確定した記録から、電子カルテに貼るための文を作る。"""

from datetime import datetime

from app.models.api import Patient
from app.models.draft import Draft, SoapSentence, Vital
from app.services.clock import JST

# 項目 → (略号, 単位)。並びはカルテに書く順（R-01：T・BP・P・R・SpO2。血糖はあれば最後）
_VITAL_FORMAT = {
    "体温": ("T", "℃"),
    "血圧": ("BP", ""),
    "脈拍": ("P", ""),
    "呼吸数": ("R", ""),
    "SpO2": ("SpO2", "%"),
    "血糖": ("BS", ""),
}


# 文の終わりとみなす文字。これで終わらない文には「。」を足す（文がつながって読めなくなるため）
_SENTENCE_END = ("。", "．", ".", "！", "!", "？", "?", "」", "』", "）", ")")


def _joined_sentences(sentences: list[SoapSentence]) -> str:
    texts = [s.text.strip() for s in sentences]
    return "".join(t if t.endswith(_SENTENCE_END) else t + "。" for t in texts if t)


def _vital_line(vitals: list[Vital]) -> str:
    by_item = {v.item: v.value for v in vitals}
    return " ".join(
        f"{abbr} {by_item[item]}{unit}"
        for item, (abbr, unit) in _VITAL_FORMAT.items()
        if item in by_item
    )


def chart_text(patient: Patient, draft: Draft, confirmed_at: datetime) -> str:
    """カルテ用の文（R-01）。患者・日時 → バイタル → S) → O) → A) → P) の順。

    先頭に患者の氏名・部屋・日時を必ず入れる（S-06）。看護師が残した根拠のない文にも
    印は出さない（A-06：カルテの書式を崩さない。印は記録のデータにだけ残す）。
    手で入力が必要なもの（薬の話）は画面で知らせ、ここには書かない。
    """
    lines = [
        f"【{patient.room}号室{patient.bed} {patient.display_name}様】"
        f"{confirmed_at.astimezone(JST):%Y-%m-%d %H:%M}",
    ]
    vital_line = _vital_line(draft.vitals)
    if vital_line:
        lines.append(vital_line)
    lines += [
        "S) " + _joined_sentences(draft.soap.S),
        "O) " + _joined_sentences(draft.soap.O),
        "A) " + draft.soap.A,
        "P) " + draft.soap.P,
    ]
    return "\n".join(lines)
