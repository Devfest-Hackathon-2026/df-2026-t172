"""確定後の手動訂正で受け取る入力。根拠や患者情報は受け取らない。"""

from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, StringConstraints

from app.models.draft import Urgency, VitalItem
from app.models.labels import DEFAULT_CATEGORY, DEFAULT_ROLE, Category, Role
from app.models.limits import MAX_ITEMS, MAX_SENTENCES, SafeId, ShortText, Text

RowIndex = Annotated[int, Field(ge=0, lt=MAX_SENTENCES, strict=True)]
LinkedTaskId = Annotated[str, StringConstraints(pattern=r"^[A-Za-z0-9_-]{1,90}$")]


class EditInput(BaseModel):
    """画面から送られた編集対象外の欄は拒否する。"""

    model_config = ConfigDict(extra="forbid")


class TextEdit(EditInput):
    """文の変更・追加。元の位置がなければ新しい文。"""

    index: RowIndex | None = None
    text: Text


class SentenceEdit(TextEdit):
    """S・O の文と看護計画。"""

    plan_id: SafeId | None = None


class VitalEdit(EditInput):
    """バイタルの項目・値。"""

    index: RowIndex | None = None
    item: VitalItem
    value: ShortText


class RequestEdit(EditInput):
    """依頼と対応する既存タスク。タスクの指定がなければ新しい依頼。"""

    task_id: LinkedTaskId | None = None
    text: Text
    urgency: Urgency = "none"
    category: Category = DEFAULT_CATEGORY
    role: Role = DEFAULT_ROLE


class SoapEdit(EditInput):
    """SOAP の変更する欄だけを指定する。"""

    S: list[SentenceEdit] | None = Field(default=None, max_length=MAX_SENTENCES)
    O: list[SentenceEdit] | None = Field(default=None, max_length=MAX_SENTENCES)  # noqa: E741
    A: Text | None = None
    P: Text | None = None


class RecordChanges(EditInput):
    """編集した欄。配列を送る欄は編集後の全行を順に入れる。"""

    soap: SoapEdit | None = None
    vitals: list[VitalEdit] | None = Field(default=None, max_length=MAX_ITEMS)
    requests: list[RequestEdit] | None = Field(default=None, max_length=MAX_ITEMS)
    manual_needed: list[TextEdit] | None = Field(default=None, max_length=MAX_ITEMS)
    doctor_questions: list[TextEdit] | None = Field(default=None, max_length=MAX_ITEMS)


class RecordAmend(EditInput):
    """読んだ版と、その版に適用する変更。"""

    revision: Annotated[int, Field(ge=0, strict=True)]
    changes: RecordChanges
