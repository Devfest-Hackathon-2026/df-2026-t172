"""POST /api/tasks（看護師がタスクを直接作る、決まり A-12）の入力の形。"""

from typing import Annotated

from pydantic import BaseModel, Field, StringConstraints

from app.models.draft import CueKind, Urgency
from app.models.labels import DEFAULT_CATEGORY, DEFAULT_ROLE, Category, Role
from app.models.limits import MAX_PATIENT_WORDS, MAX_SAVED_CHARS, MAX_TEXT_CHARS, SafeId, ShortText

PatientWord = Annotated[str, StringConstraints(max_length=MAX_SAVED_CHARS)]


class TaskCueInput(BaseModel):
    """看護師が付ける手がかり。"""

    kind: CueKind
    text: ShortText


class TaskCreate(BaseModel):
    """記録なしで作るタスク。AI を通さないので、照合も二段目もかけない。"""

    patient_id: SafeId
    text: Annotated[
        str, StringConstraints(strip_whitespace=True, min_length=1, max_length=MAX_TEXT_CHARS)
    ]
    urgency: Urgency = "none"
    category: Category = DEFAULT_CATEGORY
    role: Role = DEFAULT_ROLE
    cue: TaskCueInput | None = None
    patient_words: list[PatientWord] = Field(default_factory=list, max_length=MAX_PATIENT_WORDS)
