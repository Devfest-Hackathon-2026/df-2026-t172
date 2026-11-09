"""GET /api/records・GET /api/records/{id} の出力の形（docs/design/data-model.md の 3章）。

会話の全文は保存していないので返せない（P-02）。返すのは、確定した記録に残った
要素の根拠になった発言（evidence_utterances）だけ。
"""

from pydantic import BaseModel, Field

from app.models.api import MatchLevel, Mode
from app.models.draft import Draft, Speaker

# 一覧の要約に出す、S・O の最初の文の長さ
PREVIEW_CHARS = 60


class RecordSummary(BaseModel):
    """記録の一覧の1件（短い要約だけ）。"""

    record_id: str
    patient_id: str
    room: str
    name: str
    full_name: str = ""
    created_at: str
    s_preview: str | None = Field(description="S の最初の文（60字まで）。S がなければ null")
    o_preview: str | None = Field(description="O の最初の文（60字まで）。O がなければ null")
    request_count: int


class RecordsResponse(BaseModel):
    """GET /api/records の出力。新しい順。"""

    mode: Mode
    records: list[RecordSummary]


class EvidenceUtterance(BaseModel):
    """記録と一緒に残した、根拠になった発言（P-02）。"""

    id: str
    speaker: Speaker
    text: str


class KeptAfterCheck(BaseModel):
    """止まったのに看護師が「残す」を選んだ要素の印（A-06）。"""

    path: str
    codes: list[str]
    note: str


class PatientCheck(BaseModel):
    """患者の照合の結果と、看護師が確かめたか（S-04）。"""

    level: MatchLevel
    confirmed_by_nurse: bool
    note: str | None = None


class RecordDetail(Draft):
    """保存した記録の全体（下書きの欄に、保存のときの情報を足したもの）。"""

    record_id: str
    patient_id: str
    room: str
    name: str
    full_name: str = ""
    evidence_utterances: list[EvidenceUtterance]
    kept_after_check: list[KeptAfterCheck]
    patient_check: PatientCheck
    confirmed_reported_by: str | None = Field(
        default=None, description="確定したと申告した看護師の id（自己申告、S-08）"
    )
    created_at: str
    chart_text: str = Field(description="保存した記録から作り直したカルテ用の文")


class RecordDetailResponse(BaseModel):
    """GET /api/records/{id} の出力。"""

    mode: Mode
    record: RecordDetail
