"""文字起こしの語の列から発言の列を作るときの、記号の直し（11/8 の技術検証で出た形）。"""

import pytest

from app.checks.vital_extract import extract_vitals
from app.services.utterances import Word, normalize_transcript, utterances_from_words


@pytest.mark.parametrize(
    ("raw", "want"),
    [
        ("37.4°ちょっと高めですね。", "37.4度ちょっと高めですね。"),
        ("36.5°Cですね。", "36.5度ですね。"),
        ("36.6 ℃でした", "36.6度でした"),
        ("血圧は118-70。", "血圧は118/70。"),
        ("血圧は132 − 78", "血圧は132/78"),
        ("電話は03-1234-5678", "電話は03-1234-5678"),
        ("3-4回", "3-4回"),
        ("132の78", "132の78"),
    ],
)
def test_normalize_transcript(raw: str, want: str) -> None:
    assert normalize_transcript(raw) == want


def test_recognized_symbols_reach_vital_extraction() -> None:
    words = [
        Word("37.4°ちょっと高めですね。", 0.0, 2.0, "1"),
        Word("うん。", 2.5, 3.0, "2"),
        Word("血圧は118-70。脈は82。", 4.0, 6.0, "1"),
    ]
    first, _, third = utterances_from_words(words)
    assert extract_vitals(first.text) == {"体温": ["37.4"]}
    assert extract_vitals(third.text) == {"血圧": ["118/70"], "脈拍": ["82"]}


def test_glucose_value_in_the_next_utterance_uses_context() -> None:
    """「血糖測ってから…」と「182ですね」が間で別の発言になっても、血糖として拾う（11/8 の r2）。"""
    assert extract_vitals("182ですね。", context="じゃあ、血糖測ってから着替えましょうか。") == {
        "血糖": ["182"]
    }
    # 直前に「血糖」がなければ拾わない。時刻は直前に「血糖」があっても拾わない
    assert "血糖" not in extract_vitals("182ですね。", context="着替えましょうか")
    assert "血糖" not in extract_vitals("13時からですよ", context="血糖測りますね")
