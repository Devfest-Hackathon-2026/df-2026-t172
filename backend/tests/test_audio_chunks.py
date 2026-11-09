"""長い録音を区切って認識し、つなぎ直す（app.services.audio_chunks）。

区切りの認識の結果は手で作る（本物の Speech-to-Text は呼ばない）。
"""

import pytest

from app.services.audio_chunks import Piece, chunk_spans, stitch
from app.services.utterances import Word, utterances_from_words


@pytest.mark.parametrize(
    ("total", "spans"),
    [
        (27.8, [(0.0, 27.8)]),
        (58.0, [(0.0, 58.0)]),  # 59秒までは1回で送る
        (62.5, [(0.0, 55.0), (50.0, 62.5)]),
        (149.5, [(0.0, 55.0), (50.0, 105.0), (100.0, 149.5)]),
        (180.0, [(0.0, 55.0), (50.0, 105.0), (100.0, 155.0), (150.0, 180.0)]),
    ],
)
def test_chunk_spans_overlap_5_seconds(total: float, spans: list[tuple[float, float]]) -> None:
    assert chunk_spans(total) == spans
    assert all(end - start < 60 for start, end in spans)


def _words(*items: tuple[str, float, str]) -> list[Word]:
    """(文字, 区切りの頭からの開始の秒, ラベル)。1語は0.4秒とする。"""
    return [Word(text, start, start + 0.4, label) for text, start, label in items]


def test_labels_are_matched_by_the_overlap_and_duplicates_are_dropped() -> None:
    # 1つ目の区切り：A=看護師、B=患者。50〜55秒が重なり
    first = Piece(0.0, 55.0, _words(
        ("302号室の田中さん", 0.0, "A"), ("はい", 2.0, "B"),
        ("血圧", 51.0, "A"), ("測りますね", 51.5, "A"), ("お願い", 53.5, "B"), ("します", 54.0, "B"),
    ))  # fmt: skip
    # 2つ目の区切り：ラベルが振り直され、看護師が "1"、患者が "0" になった
    second = Piece(50.0, 70.0, _words(
        ("血圧", 1.0, "1"), ("測りますね", 1.5, "1"), ("お願い", 3.5, "0"), ("します", 4.0, "0"),
        ("132の78", 6.0, "1"), ("高い？", 8.0, "0"),
    ))  # fmt: skip
    words = stitch([first, second])
    texts = [(w.text, w.speaker_label, round(w.start, 1)) for w in words]
    assert texts == [
        ("302号室の田中さん", "A", 0.0),
        ("はい", "B", 2.0),
        ("血圧", "A", 51.0),
        ("測りますね", "A", 51.5),  # 重なりの真ん中（52.5秒）より前は前の区切りから
        ("お願い", "B", 53.5),  # 後は次の区切りから。同じ語は1回だけ
        ("します", "B", 54.0),
        ("132の78", "A", 56.0),  # 時刻は録音の頭からの通しの秒
        ("高い？", "B", 58.0),
    ]
    speakers = [(u.speaker, u.text) for u in utterances_from_words(words)]
    assert speakers[-2:] == [("nurse", "132の78"), ("patient", "高い？")]


def test_one_matched_label_decides_the_other() -> None:
    first = Piece(
        0.0, 55.0, _words(("302号室です", 0.0, "A"), ("はい", 2.0, "B"), ("それでは", 52.0, "A"))
    )
    second = Piece(50.0, 70.0, _words(("それでは", 2.0, "1"), ("うん", 6.0, "0")))
    labels = [w.speaker_label for w in stitch([first, second])]
    assert labels == ["A", "B", "A", "B"]


def test_unmatched_piece_is_decided_by_nurse_likeness() -> None:
    # 重なりに同じ言葉がない（黙っていた）。2つ目は "0" が部屋番号と体温を言う → 看護師
    first = Piece(0.0, 55.0, _words(("302号室の田中さん", 0.0, "A"), ("はい", 3.0, "B")))
    second = Piece(50.0, 80.0, _words(
        ("眠れなかった", 6.0, "1"), ("302号室", 9.0, "0"), ("36.8度ですね", 12.0, "0"),
    ))  # fmt: skip
    labels = [w.speaker_label for w in stitch([first, second])]
    assert labels == ["A", "B", "B", "A", "A"]


def test_undecided_piece_stays_unknown() -> None:
    # 重なりも看護師らしさも手がかりがない → 別のラベルのまま（話者は「不明」）
    first = Piece(0.0, 55.0, _words(("おはようございます", 0.0, "A"), ("はい", 3.0, "B")))
    second = Piece(50.0, 80.0, _words(("そうですね", 6.0, "1"), ("うん", 9.0, "0")))
    words = stitch([first, second])
    assert [w.speaker_label for w in words] == ["A", "B", "p1:1", "p1:0"]
    assert [u.speaker for u in utterances_from_words(words)] == [
        "nurse", "patient", "unknown", "unknown",
    ]  # fmt: skip
