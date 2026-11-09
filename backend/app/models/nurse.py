"""看護師の一覧と、タスクの担当（決まり S-08）。

看護師はデモ用の架空の数人で、起動時に `backend/seed/nurses.json` から読む（P-07）。
ログインはないので、担当を誰が変えたかは残せない（`assigned_set_by` は「人の手か、
最初の決まりか」だけを表す。docs/design/auth.md）。
"""

from typing import Literal

from pydantic import BaseModel

# タスクの担当が、受け持ちから写したもの（rule）か、看護師が変えたもの（nurse）か
AssignedSetBy = Literal["rule", "nurse"]


class Nurse(BaseModel):
    """看護師の1人（架空）。"""

    id: str
    name: str
    kana: str


class NursesResponse(BaseModel):
    """GET /api/nurses の出力。"""

    mode: Literal["mock", "live"]
    nurses: list[Nurse]
