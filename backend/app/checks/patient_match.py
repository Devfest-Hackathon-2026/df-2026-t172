"""選んだ患者と、会話で言われた部屋番号・名前の照合（Gemini を通さずコードで行う）。

決まり S-01・S-02（docs/design/rules.md）。会話は照合にだけ使い、患者は名簿で決める。

| 部屋番号・名前の結果 | level（色） |
|---|---|
| どちらかが「食い違い」（名簿のほかの患者の部屋番号、名簿の別の患者の名前） | stop（赤） |
| どちらかが「照合できず」（言っていない、名簿にない部屋番号＝聞き違い） | confirm（黄） |
| 同姓の患者が名簿にいて、部屋番号が一致していない | confirm（黄） |
| 部屋番号も名前も「一致」 | ok（緑） |

名前は敬称（さん・様など）の直前にあるものだけを数える。名簿の別の患者の名前は、雑談に
出ただけでも、選んだ患者の名前と一緒に出ても「食い違い」にする。赤でも看護師の確認
1回で確定できる（S-03・S-04）ので、取り違えを見逃さない側に倒す。
"""

import re
import unicodedata

from app.checks.numbers_ja import normalize
from app.models.api import MatchLevel, MatchStatus, Patient, PatientMatch
from app.models.draft import Utterance

_ROOM = re.compile(r"(?<!\d)(\d{3,4})\s*号室")


def _to_katakana(kana: str) -> str:
    """ひらがなをカタカナにする（文字起こしがカタカナで出ることがあるため）。"""
    return "".join(chr(ord(c) + 0x60) if "ぁ" <= c <= "ゖ" else c for c in kana)


# 名前として扱うのは、敬称の直前にあるものだけ（「さとうきび」の「さとう」を拾わないため）。
# 漢字の名前は、直前も漢字ならもっと長い名前の一部とみなす（名簿にない「大林さん」の「林」）。
# かなの名前は直前に助詞（「の」など）が来るので、この見方はしない
_HONORIFIC = r"(?=\s*(?:さ[ー〜~]*ん|様|さま|くん|君|ちゃん|殿))"  # 「田中さーん」も敬称
_KANJI_BEFORE = r"(?<![一-鿿々])"  # CJK 統合漢字の範囲


def _is_kana(form: str) -> bool:
    return all("ぁ" <= c <= "ゖ" or "ァ" <= c <= "ヺ" or c == "ー" for c in form)


def _name_forms(patient: Patient) -> list[str]:
    forms = {patient.name, patient.kana, _to_katakana(patient.kana)}
    return [f for f in forms if f]


def names_said(roster: list[Patient], text: str) -> set[str]:
    """会話で敬称つきで呼ばれた患者の id。

    名簿の全員の名前（漢字・ひらがな・カタカナ）を長い順に当て、当たった所は隠してから
    次を探す。「小林さん」は小林さんにだけ当たり、林さんには当たらない。
    """
    forms = sorted(
        ((form, p.id) for p in roster for form in _name_forms(p)),
        key=lambda pair: len(pair[0]),
        reverse=True,
    )
    said: set[str] = set()
    for form, patient_id in forms:
        before = "" if _is_kana(form) else _KANJI_BEFORE
        pattern = re.compile(rf"{before}{re.escape(form)}{_HONORIFIC}")
        if pattern.search(text):
            said.add(patient_id)
            text = pattern.sub(lambda m: "　" * len(m.group()), text)
    return said


def _room_status(
    selected: Patient, roster: list[Patient], text: str
) -> tuple[MatchStatus, list[str]]:
    """部屋番号の照合の結果と、名簿にない（聞き違いらしい）部屋番号。

    赤（食い違い）にするのは、名簿のほかの患者の部屋番号が出たときだけ。名簿のどの部屋でも
    ない番号（「310号室」が「315号室」と聞こえた等）は聞き違いとみなし、黄（照合できず）に
    する。聞き違いで赤が続くと、看護師が中身を見ずに確認を押す癖がつくため（11/8 の技術検証）。
    """
    rooms = set(_ROOM.findall(normalize(text)))
    listed_rooms = {p.room for p in roster}
    unlisted = sorted(rooms - listed_rooms)
    if rooms & listed_rooms - {selected.room}:
        return "食い違い", unlisted
    if rooms == {selected.room}:
        return "一致", unlisted
    return "照合できず", unlisted


def match_patient(
    selected: Patient, roster: list[Patient], utterances: list[Utterance]
) -> PatientMatch:
    """選んだ患者が、会話の中の部屋番号・名前と食い違わないか確かめる。

    Args:
        selected: 画面で選んだ患者
        roster: 名簿
        utterances: 発言の列

    Returns:
        部屋番号と名前それぞれの照合の結果、会話に出た名簿の別の患者、色（level）と理由
    """
    text = unicodedata.normalize("NFKC", "".join(u.text for u in utterances))
    room, unlisted_rooms = _room_status(selected, roster, text)
    said = names_said(roster, text)
    # 同姓の患者は名前では区別できないので、別の患者として数えない（部屋番号で見る）
    namesakes = {p.id for p in roster if p.id != selected.id and p.name == selected.name}
    others = [p.name for p in roster if p.id in said - namesakes - {selected.id}]
    selected_said = selected.id in said or bool(said & namesakes)
    name: MatchStatus = "一致" if selected_said else "照合できず"
    if others:
        name = "食い違い"

    reasons: list[str] = []
    if room == "食い違い":
        reasons.append(f"会話の部屋番号が、選んだ {selected.room}号室 と違う")
    if others:
        reasons.append(f"会話に名簿の別の患者（{'・'.join(others)}さん）の名前が出た")
    if unlisted_rooms:
        heard = "・".join(f"{r}号室" for r in unlisted_rooms)
        reasons.append(f"名簿にない部屋番号（{heard}）が聞こえた。聞き違いの可能性がある")
    elif room == "照合できず":
        reasons.append("部屋番号を会話で確かめられない")
    if name == "照合できず":
        reasons.append("名前を会話で確かめられない")
    if namesakes and room != "一致":
        reasons.append("同姓の患者がいる。部屋番号で確かめる")

    level: MatchLevel = "ok"
    if reasons:
        level = "stop" if "食い違い" in (room, name) else "confirm"
    return PatientMatch(room=room, name=name, others=others, level=level, reasons=reasons)
