"""長い録音を区切って認識し、つなぎ直す（同期の認識は1回60秒まで。11/8 の技術検証）。

区切り方：55秒ずつ。次の区切りは、前の区切りの最後の5秒を頭に重ねて始める。
最後の区切りは59秒まで伸ばしてよい（短い切れ端の区切りを作らないため）。

つなぎ方：
- 時刻は、区切りの頭からの秒に区切りの開始を足し、録音の頭からの通しの秒にする
- 話者分離のラベルは区切りごとに振り直されるので、重なった5秒の中の同じ言葉を
  突き合わせ、多く一致したラベルどうしを同じ人とする
- 重なりで決まらないとき：2人のうち片方だけ決まれば、残りは残りの人とする。
  どちらも決まらなければ、看護師らしさ（utterances.nurse_score）で決める。それでも
  決まらなければ、区切りの番号を付けた別のラベルのまま残す（話者は「不明」になる）
- 重なった所の重複した語は、重なりの真ん中より前は前の区切り、後は次の区切りから取る
"""

import difflib
from dataclasses import dataclass, replace

from app.services.utterances import Word, nurse_score

CHUNK_SECONDS = 55.0
OVERLAP_SECONDS = 5.0
LAST_CHUNK_MAX_SECONDS = 59.0  # 同期の認識の上限（60秒）より少し短く


@dataclass(frozen=True)
class Piece:
    """1つの区切りの認識の結果。words の時刻は区切りの頭からの秒、ラベルは区切りの中のもの。"""

    start: float
    end: float
    words: list[Word]


def chunk_spans(total_seconds: float) -> list[tuple[float, float]]:
    """録音を区切る (開始, 終わり) の秒の列。"""
    spans: list[tuple[float, float]] = []
    start = 0.0
    while True:
        if total_seconds - start <= LAST_CHUNK_MAX_SECONDS:
            spans.append((start, total_seconds))
            return spans
        end = start + CHUNK_SECONDS
        spans.append((start, end))
        start = end - OVERLAP_SECONDS


def _labels_in_order(words: list[Word]) -> list[str]:
    seen: list[str] = []
    for w in words:
        if w.speaker_label and w.speaker_label not in seen:
            seen.append(w.speaker_label)
    return seen


def _match_by_overlap(before: list[Word], after: list[Word]) -> dict[str, str]:
    """重なりの中の同じ言葉から、次の区切りのラベル → 前までのラベルを決める。"""
    a = [w.text for w in before]
    b = [w.text for w in after]
    votes: dict[tuple[str, str], int] = {}
    for block in difflib.SequenceMatcher(None, a, b, autojunk=False).get_matching_blocks():
        for k in range(block.size):
            old, new = before[block.a + k].speaker_label, after[block.b + k].speaker_label
            if old and new:
                votes[(new, old)] = votes.get((new, old), 0) + len(after[block.b + k].text)
    mapping: dict[str, str] = {}
    for (new, old), _ in sorted(votes.items(), key=lambda kv: -kv[1]):
        if new not in mapping and old not in mapping.values():
            mapping[new] = old
    return mapping


def _scores(words: list[Word]) -> dict[str, int]:
    """ラベルごとの看護師らしさ（同じラベルが続く語をまとめて1つの発言として数える）。"""
    scores: dict[str, int] = {}
    run: list[Word] = []
    for w in [*words, Word("", 0.0, 0.0, "\0")]:
        if run and w.speaker_label != run[0].speaker_label:
            label = run[0].speaker_label
            scores[label] = scores.get(label, 0) + nurse_score("".join(x.text for x in run))
            run = []
        run.append(w)
    return scores


def _fill_unmatched(
    mapping: dict[str, str], merged: list[Word], words: list[Word], index: int
) -> dict[str, str]:
    """重なりで決まらなかったラベルを、残りの人・看護師らしさで決める。"""
    known = _labels_in_order(merged)
    new = _labels_in_order(words)
    left_new = [n for n in new if n not in mapping]
    left_known = [k for k in known if k not in mapping.values()]
    out = dict(mapping)
    if len(left_new) == 1 and len(left_known) == 1:
        out[left_new[0]] = left_known[0]
    elif not mapping and len(new) == 2 and len(known) >= 2:
        new_scores, known_scores = _scores(words), _scores(merged)
        ranked_new = sorted(new, key=lambda n: -new_scores.get(n, 0))
        if new_scores.get(ranked_new[0], 0) > new_scores.get(ranked_new[1], 0):
            # 前までの2人は、看護師らしい順（同じなら先に話した順）に並べる
            ranked_known = sorted(known[:2], key=lambda k: -known_scores.get(k, 0))
            out.update(zip(ranked_new, ranked_known, strict=True))
    return {n: out.get(n, f"p{index}:{n}") for n in new}


def stitch(pieces: list[Piece]) -> list[Word]:
    """区切りごとの語の列を、通しの時刻・通しの話者ラベルの1つの列にする。"""
    merged: list[Word] = []
    for index, piece in enumerate(pieces):
        words = [
            replace(w, start=w.start + piece.start, end=w.end + piece.start) for w in piece.words
        ]
        if index == 0:
            merged = words
            continue
        previous_end = pieces[index - 1].end
        before = [w for w in merged if w.end > piece.start]
        after = [w for w in words if w.start < previous_end]
        labels = _fill_unmatched(_match_by_overlap(before, after), merged, words, index)
        cut = (piece.start + previous_end) / 2
        merged = [w for w in merged if w.start < cut] + [
            replace(w, speaker_label=labels.get(w.speaker_label, ""))
            for w in words
            if w.start >= cut
        ]
    return merged
