"""Gemini に返させる形（docs/design/README.md の 6章）。

Gemini には SOAP ではなく、話者つきの自由記述（narrative）で返させる。
S と O への振り分けは、話者（source）を見てコードが行う（`app.services.soap`）。
患者・抜け・緊急度は Gemini に返させない（コードで決める）。
"""

from typing import Literal

from pydantic import BaseModel, Field

from app.models.draft import CueKind, VitalItem
from app.models.labels import DEFAULT_CATEGORY, DEFAULT_ROLE, Category, Role


class GeminiVital(BaseModel):
    """会話に出た測定値。"""

    item: VitalItem
    value: str = Field(description="発言に出た数字（血圧は 132/78 の形）。言い直しがあれば後の値")
    evidence: list[str]


class GeminiNarrative(BaseModel):
    """自由記述の1文。"""

    text: str
    source: Literal["patient", "nurse"] = Field(
        description="patient=患者が言ったこと、nurse=看護師が観察・測定したこと"
    )
    evidence: list[str] = Field(description="根拠の発言番号（3つまで）。なければ空")


class GeminiCue(BaseModel):
    """看護師が順番を決める手がかり。優先度ではない。"""

    kind: CueKind
    text: str = Field(description="手がかりの中身（例: 昼食前）。優先度の語は書かない")
    evidence: list[str]


class GeminiRequest(BaseModel):
    """患者からの依頼。ラベルは仕分けのためで、優先度ではない（A-13）。"""

    text: str
    cue: GeminiCue | None
    evidence: list[str]
    # 返らなかったら「その他」（ラベルが1つ欠けただけで下書き全体を失敗にしない）
    category: Category = Field(
        default=DEFAULT_CATEGORY, description="依頼の中身の種類。一覧から1つ。迷ったら「その他」"
    )
    role: Role = Field(
        default=DEFAULT_ROLE,
        description="対応する職種（人ではない）。一覧から1つ。迷ったら「その他」",
    )


class GeminiEvidencedText(BaseModel):
    """手で入力が必要なもの・医師への確認。"""

    text: str
    evidence: list[str]


class GeminiDraft(BaseModel):
    """Gemini が返す下書き全体。"""

    vitals: list[GeminiVital]
    narrative: list[GeminiNarrative]
    requests: list[GeminiRequest]
    manual_needed: list[GeminiEvidencedText]
    doctor_questions: list[GeminiEvidencedText]


class Verdict(BaseModel):
    """二段目の確認の、1文の判定。"""

    index: int
    verdict: Literal["supported", "not_supported", "unclear"]
    reason: str


class Verdicts(BaseModel):
    """二段目の確認の、全文の判定。"""

    items: list[Verdict]
