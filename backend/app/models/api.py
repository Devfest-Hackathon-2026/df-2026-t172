"""API の入出力の形（docs/design/data-model.md の 3章）。"""

from typing import Literal

from pydantic import BaseModel, Field

from app.models.draft import Check, CueKind, Draft, EntailSeal, FirstSpeaker, Urgency, Utterance
from app.models.labels import DEFAULT_CATEGORY, DEFAULT_ROLE, Category, LabelSetBy, Role
from app.models.limits import MAX_UTTERANCES, SafeId
from app.models.nurse import AssignedSetBy

Mode = Literal["mock", "live"]
MatchStatus = Literal["一致", "食い違い", "照合できず"]
MatchLevel = Literal["ok", "confirm", "stop"]


class Patient(BaseModel):
    """名簿の1行。"""

    id: str
    room: str
    bed: str
    name: str = Field(description="名字。会話の照合に使う（「田中さん」と呼ぶため）")
    kana: str = Field(description="名字の読み（ひらがな）。会話の照合に使う")
    full_name: str = Field(default="", description="表示用のフルネーム（例「田中 一郎」）")
    full_kana: str = Field(default="", description="表示用のフルネームの読み")
    ward: str = ""
    assigned_to: str | None = Field(
        default=None,
        description="基本の受け持ちの看護師の id（S-08）。タスクの担当の初めの値になる",
    )
    assigned_reported_by: str | None = Field(
        default=None, description="受け持ちを最後に変えたと申告した看護師の id（自己申告）"
    )

    @property
    def display_name(self) -> str:
        """画面・カルテ用の文に出す名前（フルネームがなければ名字）。"""
        return self.full_name or self.name


class PatientMatch(BaseModel):
    """選んだ患者と、会話で言われた部屋番号・名前の照合（コードで行う）。"""

    room: MatchStatus
    name: MatchStatus
    others: list[str] = Field(description="会話に出た、名簿の別の患者の名前")
    level: MatchLevel
    reasons: list[str] = Field(
        default_factory=list, description="level が ok でない理由（画面にそのまま出す）"
    )


class PatientsResponse(BaseModel):
    """GET /api/patients の出力。"""

    mode: Mode
    patients: list[Patient]


class PatientAssigneePatch(BaseModel):
    """PATCH /api/patients/{id} の入力。受け持ちにする看護師の id（S-08）。"""

    assigned_to: SafeId
    reported_by: SafeId | None = Field(
        default=None, description="画面で選んだ「自分」（自己申告。本人の確かめはない、S-08）"
    )


class PatientAssigneeResponse(BaseModel):
    """PATCH /api/patients/{id} の出力。tasks_moved は一緒に担当を移したタスクの id。"""

    mode: Literal["mock", "live"]
    patient: Patient
    tasks_moved: list[str]


class TextDraftRequest(BaseModel):
    """POST /api/drafts のテキスト入力（逃げ道・テスト用）。長さは読む側で 413 にする。"""

    patient_id: SafeId
    transcript: str
    first_speaker: FirstSpeaker = Field(
        default="auto",
        description="最初に話す人（nurse/patient/auto）。行の頭に話者がないときだけ使う",
    )


class DraftResponse(BaseModel):
    """POST /api/drafts の出力。保存しない。"""

    mode: Mode
    patient: Patient
    patient_match: PatientMatch
    input: Literal["audio", "text"]
    utterances: list[Utterance]
    draft: Draft
    checks: list[Check]
    missing: list[str]
    entail_seals: list[EntailSeal] = Field(
        default_factory=list, description="二段目の判定と署名。確定のときにそのまま送り返す"
    )
    draft_token: str = Field(
        default="", description="AI が書いた要素の印（A-12）。確定のときにそのまま送り返す"
    )


class VerifyRequest(BaseModel):
    """POST /api/verify の入力。状態を持たない。"""

    utterances: list[Utterance] = Field(max_length=MAX_UTTERANCES)
    draft: Draft
    entail: bool = False


class VerifyResponse(BaseModel):
    """POST /api/verify の出力。entail=false なら entail_seals は空（前の分を使い続ける）。"""

    mode: Mode
    checks: list[Check]
    missing: list[str]
    entail_seals: list[EntailSeal] = Field(default_factory=list)


class RecordResponse(BaseModel):
    """POST /api/records の出力。"""

    mode: Mode
    record_id: str
    chart_text: str
    tasks_created: list[str]


class TaskCue(BaseModel):
    """タスクに残す手がかり（根拠の発言番号は残さない）。"""

    kind: CueKind
    text: str


class Task(BaseModel):
    """タスク画面の1件。"""

    id: str
    patient_id: str
    room: str
    name: str
    full_name: str = ""
    record_id: str | None = None
    text: str
    patient_words: list[str] = Field(
        default_factory=list,
        description="依頼の根拠になった患者の発言そのまま（文字起こし、3件・各1,000字まで）",
    )
    urgency: Urgency
    urgency_set_by: Literal["rule", "nurse"]
    # 仕分けのラベル（A-13）。前からあるタスクには入っていないので既定で埋める
    category: Category = DEFAULT_CATEGORY
    role: Role = DEFAULT_ROLE
    category_set_by: LabelSetBy = "ai"
    role_set_by: LabelSetBy = "ai"
    cue: TaskCue | None
    status: Literal["open", "done"]
    created_at: str
    done_at: str | None = None
    # 担当の看護師の id（S-08）。作ったときは患者の受け持ちを写し、看護師が変えられる
    assigned_to: str | None = None
    assigned_set_by: AssignedSetBy = "rule"
    # 担当を最後に変えたと申告した看護師の id（自己申告。ログインがないので本人の確かめはない）
    assigned_reported_by: str | None = None


class TasksResponse(BaseModel):
    """GET /api/tasks の出力。"""

    mode: Mode
    tasks: list[Task]


class TaskPatch(BaseModel):
    """PATCH /api/tasks/{id} の入力。どれか1つだけでもよい。"""

    status: Literal["open", "done"] | None = None
    urgency: Urgency | None = None
    category: Category | None = None
    role: Role | None = None
    assigned_to: SafeId | None = Field(
        default=None, description="担当に回す・自分で引き取る（看護師の一覧にある id、S-08）"
    )
    reported_by: SafeId | None = Field(
        default=None, description="画面で選んだ「自分」（自己申告。本人の確かめはない、S-08）"
    )


class TaskResponse(BaseModel):
    """PATCH /api/tasks/{id} の出力。"""

    mode: Mode
    task: Task
