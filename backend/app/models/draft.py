"""画面とやりとりする下書きの形（docs/design/data-model.md の 3章）。

Gemini が返す形（`app.models.gemini`）を、サーバーが SOAP の形に直したもの。
画面が直した下書きも、この形で `/api/verify`・`/api/records` に戻ってくる。
そのため、どの欄にも大きさの上限を付ける（SEC-04、`app.models.limits`）。
"""

from typing import Literal

from pydantic import BaseModel, Field

from app.models.labels import DEFAULT_CATEGORY, DEFAULT_ROLE, Category, Role
from app.models.limits import (
    MAX_ITEMS,
    MAX_SENTENCES,
    Evidence,
    ShortText,
    Text,
    UtteranceId,
)

VitalItem = Literal["体温", "血圧", "脈拍", "呼吸数", "SpO2", "血糖"]
# 必須のバイタル（設計 7章）。血糖は「あれば記録」なので入れない
REQUIRED_VITALS: tuple[VitalItem, ...] = ("体温", "血圧", "脈拍", "呼吸数", "SpO2")

Speaker = Literal["nurse", "patient", "unknown"]
# 画面が録音の前に選ぶ「最初に話す人」（app.services.first_speaker）
FirstSpeaker = Literal["nurse", "patient", "auto"]
Urgency = Literal["said_urgent", "timed", "none"]
CueKind = Literal["時間指定", "患者が急ぎと言った"]
# 誰が書いた要素か（A-12）。nurse は看護師が足したもので、AI 向けの照合と二段目をかけない
AddedBy = Literal["ai", "nurse"]


class Utterance(BaseModel):
    """発言の列の1つ。番号はサーバーが振る（Gemini には作らせない）。"""

    id: UtteranceId
    speaker: Speaker
    start: float | None = None
    end: float | None = None
    text: Text


class Vital(BaseModel):
    """バイタルの1項目。"""

    item: VitalItem
    value: ShortText
    evidence: Evidence = Field(default_factory=list)
    source: Literal["conversation", "manual"] = "conversation"


class SoapSentence(BaseModel):
    """S か O の1文。"""

    text: Text
    evidence: Evidence = Field(default_factory=list)
    added_by: AddedBy = "ai"


class Soap(BaseModel):
    """SOAP。AI が書くのは S と O だけ。A と P は看護師が書く欄。"""

    S: list[SoapSentence] = Field(default_factory=list, max_length=MAX_SENTENCES)
    O: list[SoapSentence] = Field(default_factory=list, max_length=MAX_SENTENCES)  # noqa: E741
    A: Text = ""
    P: Text = ""


class Cue(BaseModel):
    """看護師が順番を決める手がかり。優先度ではない。"""

    kind: CueKind
    text: Text
    evidence: Evidence = Field(default_factory=list)


class PatientRequest(BaseModel):
    """患者からの依頼。urgency は AI ではなくコードが cue から決める。"""

    text: Text
    urgency: Urgency = "none"
    cue: Cue | None = None
    evidence: Evidence = Field(default_factory=list)
    added_by: AddedBy = "ai"
    # 仕分けのラベル（A-13）。送られなければ「その他」（今の画面がそのまま動くように）
    category: Category = DEFAULT_CATEGORY
    role: Role = DEFAULT_ROLE


class EvidencedText(BaseModel):
    """根拠つきの短い文（手で入力が必要なもの・医師への確認）。"""

    text: Text
    evidence: Evidence = Field(default_factory=list)
    added_by: AddedBy = "ai"


class Draft(BaseModel):
    """看護記録の下書き。抜け（missing）はサーバーが計算するので含めない。"""

    vitals: list[Vital] = Field(default_factory=list, max_length=MAX_ITEMS)
    soap: Soap = Field(default_factory=Soap)
    requests: list[PatientRequest] = Field(default_factory=list, max_length=MAX_ITEMS)
    manual_needed: list[EvidencedText] = Field(default_factory=list, max_length=MAX_ITEMS)
    doctor_questions: list[EvidencedText] = Field(default_factory=list, max_length=MAX_ITEMS)


CheckCode = Literal[
    "no_evidence",
    "too_many_evidence",
    "unknown_evidence",
    "value_mismatch",
    "number_not_in_evidence",
    "speaker_mismatch",
    "medication",
    "priority_word",
    "duplicate_item",
    "entail_not_supported",
    "entail_unclear",
    "multiple_values",
]


class Check(BaseModel):
    """照合か二段目の確認で引っかかった1件。path で下書きのどこかを指す。"""

    path: str
    level: Literal["stop", "warn"]
    code: CheckCode
    message: str


EntailVerdict = Literal["supported", "not_supported", "unclear"]


class EntailSeal(BaseModel):
    """二段目の判定1件と、サーバーの署名（決まり A-04・A-05）。

    画面は受け取ったまま `/api/records` に送り返す。署名は文の中身・根拠の発言と
    結びついているので、文を直すと合わなくなり、確定のときに二段目を呼び直す。
    """

    path: ShortText
    verdict: EntailVerdict
    reason: ShortText
    sig: ShortText
