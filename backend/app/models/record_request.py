"""POST /api/records（確定）の入力の形（docs/design/data-model.md の 3章）。"""

from datetime import datetime
from typing import Annotated, Literal

from pydantic import AfterValidator, BaseModel, ConfigDict, Field, StrictInt

from app.models.draft import Draft, EntailSeal, Utterance
from app.models.limits import MAX_DECISIONS, MAX_UTTERANCES, SafeId, ShortText


class Decision(BaseModel):
    """引っかかった1件を残すか消すか。"""

    path: ShortText
    action: Literal["keep", "delete"]


def _iso_time(value: str | None) -> str | None:
    """ISO 8601 の時刻だけを通す（ログに任意の文字列を出さないため、P-04）。

    Raises:
        ValueError: ISO 8601 の時刻として読めない場合
    """
    if value is None:
        return None
    try:
        datetime.fromisoformat(value)
    except ValueError as e:
        raise ValueError("時刻は ISO 8601 の形で送ってください") from e
    return value


IsoTime = Annotated[str | None, Field(default=None, max_length=40), AfterValidator(_iso_time)]


class Timing(BaseModel):
    """計測用の時刻（録音の開始・終了、下書きの表示、確定）。知らない項目は捨てる。"""

    model_config = ConfigDict(extra="ignore")

    recording_started: IsoTime = None
    recording_stopped: IsoTime = None
    draft_shown: IsoTime = None
    confirmed: IsoTime = None


# 画面が数える回数。数だけを受け、文字列は受けない（P-04：会話の文・患者名を入れられないように）
UiCount = Annotated[StrictInt | None, Field(default=None, ge=0, le=100_000)]


class UiCounts(BaseModel):
    """画面でしか分からない数（設計 9章）。キーはここに決めたものだけ（ほかは 422）。"""

    model_config = ConfigDict(extra="forbid")

    edited: UiCount = None  # 看護師が直した文の数
    evidence_taps: UiCount = None  # 根拠をタップした回数


class RecordRequest(BaseModel):
    """POST /api/records の入力。

    utterances は照合のやり直しにだけ使い、全体は保存しない。コードの照合はサーバーで
    やり直し、二段目の結果は署名で裏付けられたもの（entail_seals）だけを使う。
    confirm_id は画面が確定の操作ごとに作る id。同じ id で2回送られたら上書きする。
    """

    confirm_id: SafeId
    patient_id: SafeId
    patient_confirmed: bool = False
    utterances: list[Utterance] = Field(max_length=MAX_UTTERANCES)
    draft: Draft
    entail_seals: list[EntailSeal] = Field(default_factory=list, max_length=MAX_DECISIONS)
    # /api/drafts の draft_token。ない・合わないときは、看護師が足した要素も AI の要素として照合する
    draft_token: str | None = Field(default=None, max_length=20_000)
    decisions: list[Decision] = Field(default_factory=list, max_length=MAX_DECISIONS)
    timing: Timing = Field(default_factory=Timing)
    ui_counts: UiCounts = Field(default_factory=UiCounts)
    # 確定した看護師（画面で選んだ「自分」。自己申告で、本人の確かめはない、S-08）
    reported_by: SafeId | None = None
