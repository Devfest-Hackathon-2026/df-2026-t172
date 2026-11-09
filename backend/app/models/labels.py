"""依頼（タスク）のラベル：中身の種類と、誰が対応するか（職種）（決まり A-13）。

**どちらも仮置き**。現場の看護師に聞いて差し替えるので、一覧はここ1か所にだけ書く。
ラベルは仕分けのためで、優先度ではない（緊急度は A-08 のとおりコードが cue から決める）。
迷ったら「その他」にする。職種は人ではない（個人の割り振り `assigned_to` とは別）。
"""

from typing import Literal, get_args

Category = Literal[
    "物品",
    "食事",
    "排泄",
    "移動",
    "付き添い",
    "清潔",
    "着替え",
    "体調",
    "痛みの訴え",
    "医師への確認",
    "その他",
]
Role = Literal["看護師", "看護助手", "医師", "その他"]
# ラベルを AI が付けたか、看護師が付けた・変えたか
LabelSetBy = Literal["ai", "nurse"]

CATEGORIES: tuple[str, ...] = get_args(Category)
ROLES: tuple[str, ...] = get_args(Role)
DEFAULT_CATEGORY: Category = "その他"
DEFAULT_ROLE: Role = "その他"
