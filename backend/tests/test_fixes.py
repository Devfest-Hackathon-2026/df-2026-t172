"""批判の記録 3回目の4〜8（実装しながら直す）と、SOAP・緊急度・手入力の規則。"""

import pytest

from app.checks.numbers_ja import numbers
from app.checks.patient_match import match_patient
from app.checks.verify import verify
from app.checks.vital_extract import extract_vitals
from app.models.api import Patient
from app.models.draft import Draft, Utterance, Vital
from app.services.soap import to_soap
from tests.helpers import ROSTER, draft_of, gemini_draft_of, utterances_of


def utt(*rows: tuple[str, str]) -> list[Utterance]:
    return [Utterance(id=f"u{i}", speaker=s, text=t) for i, (s, t) in enumerate(rows, 1)]  # type: ignore[arg-type]


def codes_at(draft: Draft, utterances: list[Utterance], path: str) -> set[str]:
    return {c.code for c in verify(draft, utterances).checks if c.path == path}


# --- 4. 「患者が急ぎと言った」の根拠は患者の発言に限る ---

URGENT = utt(("patient", "トイレに行きたい、早めにお願い"), ("nurse", "すぐ行きますね"))


def _urgent_request(cue_evidence: list[str]) -> Draft:
    return Draft.model_validate(
        {
            "requests": [
                {
                    "text": "トイレに行きたい",
                    "urgency": "said_urgent",
                    "cue": {
                        "kind": "患者が急ぎと言った",
                        "text": "早めに",
                        "evidence": cue_evidence,
                    },
                    "evidence": ["u1"],
                }
            ]
        }
    )


def test_A08_said_urgent_from_patient_passes() -> None:
    assert codes_at(_urgent_request(["u1"]), URGENT, "requests[0].cue") == set()


def test_A08_said_urgent_from_nurse_only_is_stopped() -> None:
    assert codes_at(_urgent_request(["u2"]), URGENT, "requests[0].cue") == {"speaker_mismatch"}


# --- 6. 薬の語の拡充と、読み替え後の文への適用 ---


@pytest.mark.parametrize(
    "text",
    ["ロキソニンを飲みたい", "点滴が気になる", "痛み止めが欲しい", "湿布を貼りたい", "夕方に二錠"],
)
def test_A07_medication_words_are_stopped(text: str) -> None:
    conv = utt(("patient", text))
    draft = Draft.model_validate({"soap": {"S": [{"text": text, "evidence": ["u1"]}]}})
    assert "medication" in codes_at(draft, conv, "soap.S[0]")


def test_medication_in_manual_needed_is_allowed() -> None:
    conv = utt(("nurse", "夕方の薬、いつもの2錠ですからね"))
    draft = Draft.model_validate(
        {"manual_needed": [{"text": "薬の話あり（2錠）", "evidence": ["u1"]}]}
    )
    assert verify(draft, conv).checks == []


# --- 7. 名簿の別の患者の名前の扱い（level の表、rules.md S-02：別の患者の名前は赤） ---

SATO = next(p for p in ROSTER if p.name == "佐藤")


@pytest.mark.parametrize(
    ("rows", "level"),
    [
        ([("nurse", "305号室の佐藤さん、検温です")], "ok"),
        (
            [
                ("nurse", "305号室の佐藤さん"),
                ("patient", "はい"),
                ("nurse", "はい"),
                ("patient", "田中さんは元気？"),
            ],
            "stop",
        ),
        ([("nurse", "305号室の佐藤さんと田中さん")], "stop"),
        ([("nurse", "305号室の田中さん")], "stop"),
        ([("nurse", "302号室の佐藤さん")], "stop"),
        ([("nurse", "失礼します")], "confirm"),
        ([("nurse", "三百五号室の佐藤さん")], "ok"),
    ],
    ids=[
        "一致",
        "雑談に別の患者",
        "冒頭に両方",
        "冒頭に別の患者だけ",
        "部屋が違う",
        "何も言わない",
        "漢数字の部屋番号",
    ],
)
def test_S02_patient_match_levels(rows: list[tuple[str, str]], level: str) -> None:
    assert match_patient(SATO, ROSTER, utt(*rows)).level == level


def test_namesake_is_not_counted_as_other_patient() -> None:
    roster = [*ROSTER, Patient(id="p399", room="399", bed="B", name="佐藤", kana="さとう")]
    match = match_patient(SATO, roster, utt(("nurse", "佐藤さん、検温です")))
    assert match.others == []
    assert match.level == "confirm"
    assert any("同姓" in r for r in match.reasons)


# --- 8. 現場の言い方・血糖・漢数字を数の文脈に限る ---


@pytest.mark.parametrize(
    ("text", "item", "value"),
    [
        ("サット98です", "SpO2", "98"),
        ("SpO2 97%", "SpO2", "97"),
        ("心拍数は72", "脈拍", "72"),
        ("上が132で下が78ですね", "血圧", "132/78"),
        ("血圧は百三十二の七十八", "血圧", "132/78"),
        ("血糖測りますね。182です", "血糖", "182"),
    ],
)
def test_field_expressions(text: str, item: str, value: str) -> None:
    assert extract_vitals(text).get(item) == [value]


def test_value_after_item_word_in_previous_utterance() -> None:
    assert extract_vitals("132の78です", context="血圧測りますね").get("血圧") == ["132/78"]


@pytest.mark.parametrize("text", ["血糖は13時に測ります", "血糖、3年生の孫が", "血糖は午後2回"])
def test_glucose_ignores_non_glucose_numbers(text: str) -> None:
    assert "血糖" not in extract_vitals(text)


@pytest.mark.parametrize("text", ["脈は十分です", "十分眠れた", "一緒に行きましょう"])
def test_kanji_words_are_not_numbers(text: str) -> None:
    assert numbers(text) == set()
    assert "脈拍" not in extract_vitals(text)


def test_spo2_word_has_no_number() -> None:
    assert numbers("SpO2 97%") == {"97"}


# --- SOAP・緊急度・手入力 ---


def test_A02_soap_split_by_speaker_and_a_p_empty() -> None:
    draft = to_soap(gemini_draft_of("s1"))
    assert [s.evidence for s in draft.soap.S] == [["u9", "u11"]]
    assert [s.evidence for s in draft.soap.O] == [["u12"]]
    assert (draft.soap.A, draft.soap.P) == ("", "")


def test_A08_urgency_from_cue_kind() -> None:
    draft = to_soap(gemini_draft_of("s2"))
    assert [r.urgency for r in draft.requests] == ["none", "timed"]
    urgent = to_soap(
        gemini_draft_of(
            "s2",
            lambda d: d["requests"][0].update(
                cue={"kind": "患者が急ぎと言った", "text": "すぐ", "evidence": ["u8"]}
            ),
        )
    )
    assert urgent.requests[0].urgency == "said_urgent"


def test_A10_A11_manual_vital_skips_conversation_and_fills_missing() -> None:
    draft = draft_of("s1")
    draft.vitals.append(Vital(item="SpO2", value="98", source="manual"))
    result = verify(draft, utterances_of("s1"))
    assert [c for c in result.checks if c.path == "vitals[3]"] == []
    assert "SpO2" not in result.missing


def test_S07_manual_vital_duplicate_with_conversation_is_stopped() -> None:
    draft = draft_of("s1")
    draft.vitals.append(Vital(item="体温", value="36.9", source="manual"))
    assert codes_at(draft, utterances_of("s1"), "vitals[3]") == {"duplicate_item"}
