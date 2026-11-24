"""カルテ用の文を看護計画ごとにまとめる（care-plan-soap の要件8、決まり R-01 の書き換え）。"""

from datetime import datetime

import pytest

from app.models.api import Patient
from app.models.care_plan import CarePlan
from app.models.draft import Draft, Soap, SoapSentence, Vital
from app.services.chart import chart_text
from app.services.clock import JST
from app.services.mock_data import load_mock_draft, load_patients, load_scenarios
from app.services.record_documents import record_document

# ---- 直す前の services/chart.py の写し（以後は変えない。今の形と1字も違わないかを見る） ----
_VITAL_FORMAT = {
    "体温": ("T", "℃"),
    "血圧": ("BP", ""),
    "脈拍": ("P", ""),
    "呼吸数": ("R", ""),
    "SpO2": ("SpO2", "%"),
    "血糖": ("BS", ""),
}
_SENTENCE_END = ("。", "．", ".", "！", "!", "？", "?", "」", "』", "）", ")")


def _joined(sentences: list[SoapSentence]) -> str:
    texts = [s.text.strip() for s in sentences]
    return "".join(t if t.endswith(_SENTENCE_END) else t + "。" for t in texts if t)


def legacy_chart_text(patient: Patient, draft: Draft, confirmed_at: datetime) -> str:
    """直す前の chart_text。"""
    lines = [
        f"【{patient.room}号室{patient.bed} {patient.display_name}様】"
        f"{confirmed_at.astimezone(JST):%Y-%m-%d %H:%M}",
    ]
    by_item = {v.item: v.value for v in draft.vitals}
    vital_line = " ".join(
        f"{abbr} {by_item[item]}{unit}"
        for item, (abbr, unit) in _VITAL_FORMAT.items()
        if item in by_item
    )
    if vital_line:
        lines.append(vital_line)
    lines += [
        "S) " + _joined(draft.soap.S),
        "O) " + _joined(draft.soap.O),
        "A) " + draft.soap.A,
        "P) " + draft.soap.P,
    ]
    return "\n".join(lines)


# ---------------------------------------------------------------------------------------------

AT = datetime(2026, 11, 19, 10, 0, tzinfo=JST)
ROSTER = {p.id: p for p in load_patients()}
P305 = ROSTER["p305"]
NO_PLANS = P305.model_copy(update={"care_plans": []})


def _s(text: str, plan_id: str | None = None) -> SoapSentence:
    return SoapSentence(text=text, plan_id=plan_id)


def _draft(s: list[SoapSentence], o: list[SoapSentence] | None = None, **kw: object) -> Draft:
    return Draft(soap=Soap(S=s, O=o or []), **kw)  # type: ignore[arg-type]


_EDGE_DRAFTS = [
    _draft([]),
    _draft([_s("  ")], [_s("")]),
    _draft([_s("句点なし")], [_s("ある。")]),
    _draft([_s("   ", "cp04"), _s("ふつうの文。")]),  # 空白だけの文にだけ plan_id
    Draft.model_validate({"soap": {"S": [{"text": "欄なし。"}], "O": []}}),
]


# Feature: care-plan-soap, Property 6: plan_id がなければ今の形と1字も違わない
@pytest.mark.parametrize("patient", [P305, NO_PLANS], ids=["with_plans", "no_plans"])
@pytest.mark.parametrize(
    "draft",
    [load_mock_draft(sc["id"]).draft for sc in load_scenarios()] + _EDGE_DRAFTS,
)
def test_R01_chart_unchanged_without_plan_ids(patient: Patient, draft: Draft) -> None:
    assert chart_text(patient, draft, AT) == legacy_chart_text(patient, draft, AT)


HEAD = "【305号室A 佐藤 和夫様】2026-11-19 10:00"
TWO_PLANS = P305  # cp04 #急性疼痛、cp05 #活動耐性低下


# Feature: care-plan-soap, Property 7: 看護計画ごとの欄
@pytest.mark.parametrize(
    ("draft", "patient", "expected"),
    [
        (  # (a) 2つの計画と計画外
            _draft([_s("痛い。", "cp04"), _s("眠れない。"), _s("きつい。", "cp05")], [_s("O1。", "cp04")]),
            TWO_PLANS,
            [HEAD, "#急性疼痛", "S) 痛い。", "O) O1。", "#活動耐性低下", "S) きつい。", "計画外", "S) 眠れない。", "A) ", "P) "],
        ),
        (  # (b) O だけの計画
            _draft([_s("眠れない。")], [_s("発赤なし", "cp04")]),
            TWO_PLANS,
            [HEAD, "#急性疼痛", "O) 発赤なし。", "計画外", "S) 眠れない。", "A) ", "P) "],
        ),
        (  # (c) 計画外がない
            _draft([_s("痛い。", "cp04")]),
            TWO_PLANS,
            [HEAD, "#急性疼痛", "S) 痛い。", "A) ", "P) "],
        ),
        (  # (d) 名簿にない plan_id は計画外の欄
            _draft([_s("痛い。", "cp99"), _s("眠れない。")]),
            TWO_PLANS,
            [HEAD, "計画外", "S) 痛い。眠れない。", "A) ", "P) "],
        ),
        (  # (e) 患者に計画がない
            _draft([_s("痛い。", "cp04")]),
            NO_PLANS,
            [HEAD, "計画外", "S) 痛い。", "A) ", "P) "],
        ),
        (  # (f) 文の付かない計画は見出しも出ない。並びは care_plans の順
            _draft([_s("きつい。", "cp05"), _s("痛い。", "cp04")]),
            TWO_PLANS,
            [HEAD, "#急性疼痛", "S) 痛い。", "#活動耐性低下", "S) きつい。", "A) ", "P) "],
        ),
    ],
)  # fmt: skip
def test_R01_chart_groups_by_care_plan(draft: Draft, patient: Patient, expected: list[str]) -> None:
    text = chart_text(patient, draft, AT)
    assert text.split("\n") == expected
    for s in draft.soap.S + draft.soap.O:
        body = s.text.strip()
        assert sum(line.count(body) for line in text.split("\n")) == 1


def test_R01_chart_305_script_example() -> None:
    """(g) requirements の 305号室の例（8行）と1字も違わない。"""
    draft = _draft(
        [
            _s("起き上がるときに術創がズキッとする。痛みは10段階で4。", "cp04"),
            _s("夜中に2回トイレで起き、あまり眠れなかった"),
            _s("朝食は半分で、食欲がない。"),
        ],
        vitals=[
            Vital(item="体温", value="37.2"),
            Vital(item="血圧", value="132/84"),
            Vital(item="脈拍", value="88"),
        ],
    )
    assert chart_text(P305, draft, AT) == (
        "【305号室A 佐藤 和夫様】2026-11-19 10:00\n"
        "T 37.2℃ BP 132/84 P 88\n"
        "#急性疼痛\n"
        "S) 起き上がるときに術創がズキッとする。痛みは10段階で4。\n"
        "計画外\n"
        "S) 夜中に2回トイレで起き、あまり眠れなかった。朝食は半分で、食欲がない。\n"
        "A) \n"
        "P) "
    )


# Feature: care-plan-soap, Property 8: 保存して読み直しても plan_id と chart_text は同じ
@pytest.mark.parametrize(
    "draft",
    [
        _draft([_s("痛い。", "cp04"), _s("眠れない。")], [_s("O1。", "cp05")]),
        _draft([_s("痛い。", "cp99")]),
        _draft([_s("痛い。"), _s("眠れない。")]),
    ],
)
def test_R01_chart_round_trip(draft: Draft) -> None:
    record = record_document(
        patient=P305,
        draft=draft,
        task_ids=[],
        utterances=[],
        decisions=[],
        kept=[],
        patient_check_doc={"level": "ok", "confirmed_by_nurse": False, "note": None},
        now=AT,
    )
    reread = Draft.model_validate(record)
    assert [s.plan_id for s in reread.soap.S + reread.soap.O] == [
        s.plan_id for s in draft.soap.S + draft.soap.O
    ]
    assert chart_text(P305, reread, AT) == chart_text(P305, draft, AT)


def test_care_plans_on_patient() -> None:
    assert P305.care_plans == [
        CarePlan(id="cp04", label="#急性疼痛"),
        CarePlan(id="cp05", label="#活動耐性低下"),
    ]
