"""患者ごとの看護計画（名簿に持たせる。care-plan-soap の要件1、決まり SEC-04・P-07）。

条件に合わない看護計画は、pydantic の検証で例外にする。名簿seed を読むとき
（`app.services.mock_data.load_patients`）に起動を止めるため。エラーの文に
看護計画の名前（label）を入れない（P-04）。
"""

from typing import Annotated

from pydantic import AfterValidator, BaseModel, BeforeValidator, Field, StringConstraints

from app.models.limits import MAX_CARE_PLAN_LABEL_CHARS, MAX_CARE_PLANS, SafeId


def _one_line_label(label: str) -> str:
    """改行を含まず、空白だけでない名前だけを通す。

    Raises:
        ValueError: 改行を含む、または空白（半角・全角のスペースなど）だけの場合
    """
    if label.splitlines() != [label]:
        raise ValueError("看護計画の名前に改行は入れられません")
    if not label.strip():
        raise ValueError("看護計画の名前が空白だけです")
    return label


CarePlanLabel = Annotated[
    str,
    StringConstraints(min_length=1, max_length=MAX_CARE_PLAN_LABEL_CHARS),
    AfterValidator(_one_line_label),
]


class CarePlan(BaseModel):
    """看護計画の1件。id は名簿全体で重ならない（名簿全体の確かめは load_patients）。"""

    id: SafeId
    label: CarePlanLabel


def _none_as_empty(value: object) -> object:
    """欄が null のときは空の並びにする（要件2の2）。"""
    return [] if value is None else value


def _unique_in_patient(plans: list[CarePlan]) -> list[CarePlan]:
    """1人の患者の中で id と label が重ならないかを確かめる。

    Raises:
        ValueError: 同じ id、または同じ label が2つ以上ある場合
    """
    if len({p.id for p in plans}) != len(plans):
        raise ValueError("1人の患者の中で、看護計画の id が重なっています")
    if len({p.label for p in plans}) != len(plans):
        raise ValueError("1人の患者の中で、看護計画の名前が重なっています")
    return plans


CarePlans = Annotated[
    list[CarePlan],
    BeforeValidator(_none_as_empty),
    Field(max_length=MAX_CARE_PLANS),
    AfterValidator(_unique_in_patient),
]
