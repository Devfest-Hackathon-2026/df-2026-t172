"""本番の層で止まる、患者の照合と数の読み替え（spike/test_checks.py の30件の残り）。"""

import pytest

from app.checks.numbers_ja import numbers
from app.checks.patient_match import match_patient
from app.models.api import Patient
from app.models.draft import Utterance
from tests.helpers import ROSTER, utterances_of


def test_S02_neighbor_row_selected_is_stopped() -> None:
    wrong = next(p for p in ROSTER if p.name == "中田")
    m = match_patient(wrong, ROSTER, utterances_of("s1"))
    assert (m.room, m.name, m.level) == ("食い違い", "食い違い", "stop")


def test_S02_name_not_said_needs_confirmation() -> None:
    selected = next(p for p in ROSTER if p.room == "310")
    m = match_patient(selected, ROSTER, utterances_of("s4"))
    assert (m.name, m.level) == ("照合できず", "confirm")


@pytest.mark.parametrize(
    ("raw", "want"),
    [
        ("三十六度八分", "36.8"),
        ("３６．８度", "36.8"),
        ("36・8度", "36.8"),
        ("三十六点八度", "36.8"),
        ("千二百", "1200"),
    ],
)
def test_number_normalization(raw: str, want: str) -> None:
    assert want in numbers(raw)


def test_mou_ichido_is_not_a_decimal() -> None:
    assert "1.2" not in numbers("もう一度2分待って")


# 名前が別の名前を含む組（林／小林）と、ひらがなが普通の言葉に紛れる名前のある名簿
TRICKY_ROSTER = [
    Patient(id="p312", room="312", bed="A", name="小林", kana="こばやし"),
    Patient(id="p313", room="313", bed="A", name="林", kana="はやし"),
    Patient(id="p314", room="314", bed="A", name="佐藤", kana="さとう"),
    Patient(id="p315", room="315", bed="A", name="中田", kana="なかた"),
]
KOBAYASHI = TRICKY_ROSTER[0]


def _nurse(text: str) -> list[Utterance]:
    return [Utterance(id="u1", speaker="nurse", text=text)]


@pytest.mark.parametrize(
    "text",
    [
        "312号室の小林さん、検温です",
        "312号室の小林さん、さとうきび畑の歌が好きなんですね",
        "312号室の小林さん。おなかたいらですね",
        "312号室のこばやしさん、検温です",
        "312号室の小林さーん、起きてますか",
    ],
    ids=[
        "小林の中の林",
        "さとうきびの中のさとう",
        "おなかたいらの中のなかた",
        "ひらがなで呼ぶ",
        "さーん",
    ],
)
def test_S02_name_inside_other_word_is_not_another_patient(text: str) -> None:
    m = match_patient(KOBAYASHI, TRICKY_ROSTER, _nurse(text))
    assert (m.name, m.others, m.level) == ("一致", [], "ok")


@pytest.mark.parametrize(
    ("text", "others"),
    [
        ("312号室の林さん、検温です", ["林"]),
        ("312号室の小林さん、隣の林さんは元気ですよ", ["林"]),
        ("312号室の小林さん、さとうさんが呼んでます", ["佐藤"]),
    ],
    ids=["林さんだけ", "小林さんと林さんの両方", "ひらがなで別の患者"],
)
def test_S02_another_patient_called_by_name_is_stop(text: str, others: list[str]) -> None:
    m = match_patient(KOBAYASHI, TRICKY_ROSTER, _nurse(text))
    assert (m.others, m.level) == (others, "stop")


def test_S02_name_without_honorific_is_not_used() -> None:
    m = match_patient(KOBAYASHI, TRICKY_ROSTER, _nurse("312号室です。小林の件で来ました"))
    assert (m.name, m.level) == ("照合できず", "confirm")


def test_S02_kanji_name_inside_unlisted_longer_name_is_ignored() -> None:
    m = match_patient(KOBAYASHI, TRICKY_ROSTER, _nurse("312号室の小林さん、大林さんの話です"))
    assert (m.others, m.level) == ([], "ok")


@pytest.mark.parametrize(
    ("text", "level", "room"),
    [
        ("319号室の小林さん、検温です", "confirm", "照合できず"),  # 名簿にない＝聞き違い
        ("312号室の小林さん。319号室でしたっけ", "confirm", "照合できず"),
        ("313号室の小林さん、検温です", "stop", "食い違い"),  # 名簿の林さんの部屋
    ],
    ids=["名簿にない部屋番号は黄", "選んだ部屋と名簿にない部屋", "名簿のほかの患者の部屋は赤"],
)
def test_S02_unlisted_room_number_is_yellow(text: str, level: str, room: str) -> None:
    m = match_patient(KOBAYASHI, TRICKY_ROSTER, _nurse(text))
    assert (m.room, m.level) == (room, level)
    if room == "照合できず":
        assert any("319号室" in r and "聞き違い" in r for r in m.reasons)
