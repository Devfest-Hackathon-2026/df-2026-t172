"""看護計画のデータの形と、名簿seed の看護計画（care-plan-soap の要件1・3）。"""

import json
import unicodedata
from typing import Any

import pytest
from pydantic import ValidationError

from app.models.draft import SoapSentence
from app.services.mock_data import SEED_PATIENTS

UNPLANNED_HEADING = "計画外"


# Feature: care-plan-soap, Property 2: plan_id の形
@pytest.mark.parametrize(
    ("given", "expected"),
    [
        ({}, None),  # 欄なし
        ({"plan_id": None}, None),
        ({"plan_id": "cp01"}, "cp01"),
        ({"plan_id": "a" * 40}, "a" * 40),
        ({"plan_id": "cp_01-x"}, "cp_01-x"),
    ],
)
def test_R03_plan_id_form(given: dict[str, Any], expected: str | None) -> None:
    sentence = SoapSentence.model_validate({"text": "倦怠感の訴え。", **given})
    assert sentence.plan_id == expected


@pytest.mark.parametrize("bad", ["", "a" * 41, "cp 01", "cp/01", "ｃｐ01", 5, 1.5, True, [], {}])
def test_R03_plan_id_form_rejects(bad: object) -> None:
    with pytest.raises(ValidationError) as caught:
        SoapSentence.model_validate({"text": "倦怠感の訴え。", "plan_id": bad})
    errors = caught.value.errors()
    assert len(errors) == 1
    assert errors[0]["loc"][0] == "plan_id"


def _seed() -> list[dict[str, Any]]:
    return json.loads(SEED_PATIENTS.read_text(encoding="utf-8"))


def label_problems(patients: list[dict[str, Any]]) -> list[str]:
    """名簿の看護計画の名前のうち、見分けにくいものの場所（要件1の10）。"""
    problems = []
    for p in patients:
        seen: set[str] = set()
        for i, plan in enumerate(p["care_plans"]):
            label = plan["label"]
            where = f"{p['id']}.care_plans[{i}]"
            if label != label.strip():
                problems.append(f"{where}: 前後の空白")
            if label.strip() == UNPLANNED_HEADING:
                problems.append(f"{where}: 計画外")
            key = unicodedata.normalize("NFKC", label).strip()
            if key in seen:
                problems.append(f"{where}: 重なり")
            seen.add(key)
    return problems


def test_P07_seed_care_plans_shape() -> None:
    patients = _seed()
    assert len(patients) == 6
    ids = []
    for p in patients:
        assert isinstance(p["care_plans"], list) and len(p["care_plans"]) >= 1
        for plan in p["care_plans"]:
            assert set(plan) == {"id", "label"}
            assert plan["id"].startswith("cp") and plan["id"][2:].isdigit()
            assert len(plan["id"]) == 4
            ids.append(plan["id"])
    assert len(ids) == len(set(ids))  # 名簿全体で重ならない


def test_P07_seed_care_plan_labels_distinct() -> None:
    assert label_problems(_seed()) == []


@pytest.mark.parametrize(
    ("labels", "problem"),
    [
        (["#急性疼痛 "], "前後の空白"),
        (["計画外"], "計画外"),
        (["#急性疼痛", "＃急性疼痛"], "重なり"),
    ],
)
def test_P07_seed_care_plan_labels_distinct_rejects(labels: list[str], problem: str) -> None:
    broken = [
        {"id": "p999", "care_plans": [{"id": f"cp9{i}", "label": x} for i, x in enumerate(labels)]}
    ]
    found = label_problems(broken)
    assert len(found) == 1 and found[0].endswith(problem)


def test_S08_seed_p305_has_acute_pain() -> None:
    p305 = next(p for p in _seed() if p["id"] == "p305")
    assert [x for x in p305["care_plans"] if x == {"id": "cp04", "label": "#急性疼痛"}] == [
        {"id": "cp04", "label": "#急性疼痛"}
    ]


# 直す前の backend/seed/patients.json から写した値（care_plans 以外の欄は変えない、要件1の8）
_BEFORE = [
    ("p302", "302", "A", "田中", "たなか", "田中 一郎", "たなか いちろう", "n01"),
    ("p303", "303", "A", "中田", "なかた", "中田 花子", "なかた はなこ", "n01"),
    ("p305", "305", "A", "佐藤", "さとう", "佐藤 和夫", "さとう かずお", "n02"),
    ("p308", "308", "A", "鈴原", "すずはら", "鈴原 キヨ", "すずはら きよ", "n02"),
    ("p310", "310", "A", "小川", "おがわ", "小川 健一", "おがわ けんいち", "n03"),
    ("p312", "312", "A", "小林", "こばやし", "小林 正雄", "こばやし まさお", "n03"),
]


def test_S08_seed_other_fields_unchanged() -> None:
    keys = ("id", "room", "bed", "name", "kana", "full_name", "full_kana", "assigned_to")
    got = [tuple(p[k] for k in keys) for p in _seed()]
    assert got == _BEFORE
    assert all(p["ward"] == "東3病棟" for p in _seed())
    assert all(set(p) == {*keys, "ward", "care_plans"} for p in _seed())


# ---- 起動時の確かめ（要件1の9、SEC-04） ----

import logging  # noqa: E402
from pathlib import Path  # noqa: E402

from app.container import build_services  # noqa: E402
from app.services import mock_data  # noqa: E402
from app.services.mock_data import SeedInvalidError, load_patients  # noqa: E402
from tests.helpers import make_settings  # noqa: E402


def _with_plans(*plans_per_patient: list[dict[str, Any]]) -> list[dict[str, Any]]:
    seed = _seed()
    for p, plans in zip(seed, plans_per_patient, strict=False):
        p["care_plans"] = plans
    return seed


def _write(tmp_path: Path, seed: list[dict[str, Any]]) -> Path:
    path = tmp_path / "patients.json"
    path.write_text(json.dumps(seed, ensure_ascii=False), encoding="utf-8")
    return path


def _plans(n: int, start: int = 10) -> list[dict[str, str]]:
    return [{"id": f"cp{start + i}", "label": f"#計画{i}"} for i in range(n)]


# Feature: care-plan-soap, Property 1: 名簿seed の看護計画の条件
@pytest.mark.parametrize(
    "plans",
    [[], _plans(10), [{"id": "cp10", "label": "あ" * 100}]],
    ids=["zero", "ten", "label100"],
)
def test_SEC04_seed_care_plan_conditions_ok(
    plans: list[dict[str, str]], tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(mock_data, "SEED_PATIENTS", _write(tmp_path, _with_plans(plans)))
    assert [c.model_dump() for c in load_patients()[0].care_plans] == plans


BAD_FIRST_PATIENT = {
    "eleven": _plans(11),
    "empty_label": [{"id": "cp10", "label": ""}],
    "label101": [{"id": "cp10", "label": "あ" * 101}],
    "newline": [{"id": "cp10", "label": "#急性\n疼痛"}],
    "cr": [{"id": "cp10", "label": "#急性\r疼痛"}],
    "u2028": [{"id": "cp10", "label": "#急性\u2028疼痛"}],
    "fullwidth_space_only": [{"id": "cp10", "label": "\u3000\u3000"}],
    "id_with_space": [{"id": "cp 10", "label": "#計画"}],
    "id41": [{"id": "c" * 41, "label": "#計画"}],
    "same_id": [{"id": "cp10", "label": "#計画A"}, {"id": "cp10", "label": "#計画B"}],
    "same_label": [{"id": "cp10", "label": "#計画"}, {"id": "cp11", "label": "#計画"}],
}


@pytest.mark.parametrize("name", list(BAD_FIRST_PATIENT))
def test_SEC04_seed_care_plan_conditions_rejects(
    name: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    plans = BAD_FIRST_PATIENT[name]
    monkeypatch.setattr(mock_data, "SEED_PATIENTS", _write(tmp_path, _with_plans(plans)))
    with caplog.at_level(logging.INFO), pytest.raises(SeedInvalidError):
        load_patients()
    logs = "\n".join(r.getMessage() for r in caplog.records)
    assert '"seed_invalid"' in logs
    for plan in plans:
        if plan["label"].strip():
            assert plan["label"] not in logs
        assert f'"{plan["id"]}"' not in logs


def test_SEC04_seed_same_id_across_patients_rejects(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    seed = _with_plans([{"id": "cp10", "label": "#計画A"}], [{"id": "cp10", "label": "#計画B"}])
    monkeypatch.setattr(mock_data, "SEED_PATIENTS", _write(tmp_path, seed))
    with caplog.at_level(logging.INFO), pytest.raises(SeedInvalidError):
        load_patients()
    [line] = [
        json.loads(r.getMessage()) for r in caplog.records if "seed_invalid" in r.getMessage()
    ]
    assert line["errors"] == [
        {"index": 1, "loc": "care_plans.0.id", "type": "duplicate_care_plan_id"}
    ]
    assert "cp10" not in json.dumps(line)


@pytest.mark.parametrize(
    ("mode", "plans_a", "plans_b"),
    [
        ("mock", [{"id": "cp10", "label": "あ" * 101}], []),
        ("mock", [{"id": "cp10", "label": "#A"}], [{"id": "cp10", "label": "#B"}]),
        ("live", [{"id": "cp10", "label": "あ" * 101}], []),
    ],
)
def test_SEC04_bad_seed_stops_startup(
    mode: str,
    plans_a: list[dict[str, str]],
    plans_b: list[dict[str, str]],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(mock_data, "SEED_PATIENTS", _write(tmp_path, _with_plans(plans_a, plans_b)))

    def no_connect(*_: object, **__: object) -> None:
        raise AssertionError("Firestore につないではいけない")

    from app.store import firestore_store

    monkeypatch.setattr(firestore_store.FirestoreStore, "connect", classmethod(no_connect))
    with pytest.raises(SeedInvalidError):
        build_services(make_settings(mode))
