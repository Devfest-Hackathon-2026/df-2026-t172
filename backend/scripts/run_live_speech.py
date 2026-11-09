"""技術検証：録音を本物の Speech-to-Text V2 に通し、発言の列と照合の結果を見る。

**費用がかかる（--dry-run と --probe を除く）。実行の前にCさんの承認を取る。**
1回の認識で音声の秒数ぶん課金される（1秒単位で切り上げ）。認証は ADC。

確かめること（設計 5章の【要検証】）:
- 日本語の話者分離が、このモデル・リージョンの同期の認識（recognize）で返るか
- 60秒を超える音声を、本番と同じく55秒ずつ5秒重ねて区切り、話者を通しで対応づけられるか
- 最初に話した人を看護師にする割り当てが合うか（患者が先に話す録音 r4）
- 発言の区切り・時刻・数字が、照合（app/checks）に通る形で出るか。
  Gemini は呼ばず、場面の見本の下書きの根拠を、音声の発言番号に付け替えて照合する

使い方（backend/ で。音声と結果はリポジトリの外に置く。P-01）:
    python -m scripts.run_live_speech --probe
    python -m scripts.run_live_speech --recording r1 --dry-run --out 結果のフォルダ
    python -m scripts.run_live_speech --recording r1 --audio 録音.webm --out 結果のフォルダ
    python -m scripts.run_live_speech --recording r3 --audio 録音.m4a --max-calls 3 --out ...
"""

import argparse
import difflib
import json
import re
import secrets
import sys
import time
import unicodedata
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from app.checks.numbers_ja import ordered_numbers
from app.config import BACKEND_DIR
from app.live.mock_gemini import MockGemini
from app.live.speech_v2 import GoogleSpeech
from app.models.draft import Utterance
from app.services.audio_chunks import stitch
from app.services.drafting import build_draft
from app.services.entail_seal import EntailSealer
from app.services.mock_data import load_patients, load_scenarios
from app.services.utterances import Word, utterances_from_words

REPO_DIR = BACKEND_DIR.parent
MAX_CALLS = 1  # 承認を取った認識の回数。これを超える前に止める
MAX_AUDIO_BYTES = 10 * 1024 * 1024  # SEC-04

# 録音ごとの台本：(場面, 発言の順)。順を省くと台本どおり。r4 は患者が先に話す
RECORDINGS: dict[str, list[tuple[str, list[str] | None]]] = {
    "r1": [("s3", None)],
    "r2": [("s2", None)],
    "r3": [("s1", None), ("s5", None)],
    "r4": [("s4", ["u2", "u1", "u3", "u4", "u5", "u6"])],
}


@dataclass(frozen=True)
class ScriptLine:
    """台本の1発言。key は「場面:番号」（例 s1:u7）。"""

    key: str
    speaker: str
    text: str


def script_lines(recording: str) -> list[ScriptLine]:
    """録音で読む台本の発言を、読む順に並べる。"""
    scenarios = {s["id"]: s for s in load_scenarios()}
    lines = []
    for scenario_id, order in RECORDINGS[recording]:
        by_id = {u["id"]: u for u in scenarios[scenario_id]["utterances"]}
        for uid in order or list(by_id):
            u = by_id[uid]
            lines.append(ScriptLine(f"{scenario_id}:{uid}", u["speaker"], u["text"]))
    return lines


# ---- 認識（本番と同じ道：FLAC に直す → 55秒ずつ5秒重ねて区切る → つなぐ） ----


def recognize(
    speech: GoogleSpeech, audio: bytes, max_calls: int
) -> tuple[list[Word], list[dict], float]:
    """本番の GoogleSpeech.prepare・recognize_pieces・stitch を通す。"""
    prepared = speech.prepare(audio)
    if prepared.calls > max_calls:
        sys.exit(f"認識が{prepared.calls}回になり、承認した{max_calls}回を超える")
    pieces = speech.recognize_pieces(prepared)
    raws = [
        {
            "piece": i,
            "start": p.start,
            "end": p.end,
            "words": len(p.words),
            "labels": sorted({w.speaker_label for w in p.words}),
        }
        for i, p in enumerate(pieces)
    ]
    return stitch(pieces), raws, prepared.seconds


def dry_run_words(lines: list[ScriptLine]) -> list[Word]:
    """費用をかけずに流れを確かめる：台本を、話者ラベルつきの語の列として扱う。"""
    words, t = [], 0.0
    for line in lines:
        length = len(line.text) / 5  # 毎分300字
        words.append(Word(line.text, t, t + length, "1" if line.speaker == "nurse" else "2"))
        t += length + 0.6
    return words


# ---- 台本との突き合わせ ----


def _normalize(text: str) -> str:
    """比べるために、全角を半角にし、句読点・空白を除く。"""
    text = unicodedata.normalize("NFKC", text)
    return re.sub(r"[\s、。，．,.!?！？「」ー〜~]", "", text)


def align(utterances: list[Utterance], lines: list[ScriptLine]) -> dict[str, list[str]]:
    """音声の発言ごとに、対応する台本の発言の key を返す（文字の対応で決める）。

    台本の文字を一列に並べて音声の文字と突き合わせ、音声の発言の文字のうち
    3割以上が対応した台本の発言を、その発言に当たるとする。
    """
    script_text, script_owner = "", []
    for line in lines:
        norm = _normalize(line.text)
        script_text += norm
        script_owner += [line.key] * len(norm)
    audio_text, audio_owner = "", []
    for u in utterances:
        norm = _normalize(u.text)
        audio_text += norm
        audio_owner += [u.id] * len(norm)
    counts: dict[str, dict[str, int]] = {u.id: {} for u in utterances}
    matcher = difflib.SequenceMatcher(None, audio_text, script_text, autojunk=False)
    for a, b, size in matcher.get_matching_blocks():
        for k in range(size):
            owner = counts[audio_owner[a + k]]
            key = script_owner[b + k]
            owner[key] = owner.get(key, 0) + 1
    lengths = {u.id: max(len(_normalize(u.text)), 1) for u in utterances}
    return {
        uid: [k for k, n in c.items() if n >= 0.3 * lengths[uid] or n >= 8]
        for uid, c in counts.items()
    }


def speaker_report(
    utterances: list[Utterance], mapping: dict[str, list[str]], lines: list[ScriptLine]
) -> dict:
    """話者の当たり（文字数の重み）。入れ替えたほうが当たるなら、割り当てが逆。"""
    want = {line.key: line.speaker for line in lines}
    ok = swapped = total = 0
    mixed = []
    for u in utterances:
        speakers = {want[k] for k in mapping[u.id]}
        if len(speakers) > 1:
            mixed.append(u.id)  # 看護師と患者の発言が1つにまとまった
        if len(speakers) != 1 or u.speaker == "unknown":
            continue
        n = len(_normalize(u.text))
        total += n
        ok += n * (u.speaker in speakers)
        swapped += n * ({"nurse": "patient", "patient": "nurse"}[u.speaker] in speakers)
    return {
        "accuracy": round(ok / total, 3) if total else None,
        "accuracy_if_swapped": round(swapped / total, 3) if total else None,
        "unknown": [u.id for u in utterances if u.speaker == "unknown"],
        "mixed_speakers": mixed,
    }


def number_report(
    utterances: list[Utterance], mapping: dict[str, list[str]], lines: list[ScriptLine]
) -> list[dict]:
    """台本の数（36.8、132の78 など）が、対応する音声の発言に同じ並びで出たか。

    「132の78」が「132/78」や「百三十二の七十八」になっても、数の並びが同じなら通す。
    """
    text_of = {u.id: u.text for u in utterances}
    out = []
    for line in lines:
        want = ordered_numbers(line.text)
        if not want:
            continue
        ids = [uid for uid, keys in mapping.items() if line.key in keys]
        got = ordered_numbers(" ".join(text_of[i] for i in ids))
        # 同じ話者の続く発言は1つにまとまるので、台本の数が同じ並びで続いて出ればよい
        ok = any(got[i : i + len(want)] == want for i in range(len(got) - len(want) + 1))
        out.append({"script": line.key, "want": want, "got": got, "ok": ok, "audio": ids})
    return out


# ---- 照合（見本の下書きの根拠を、音声の発言番号に付け替える） ----


def remap_draft(
    scenario_id: str, mapping: dict[str, list[str]]
) -> tuple[dict, dict[str, str], list[str]]:
    """場面の見本の下書き（Gemini の形）の根拠を、音声の発言番号に付け替える。

    Returns:
        (付け替えた下書き, 二段目で not_supported にする文, 対応が見つからなかった根拠)
    """
    scenario = next(s for s in load_scenarios() if s["id"] == scenario_id)
    to_audio: dict[str, list[str]] = {}
    for uid, keys in mapping.items():
        for key in keys:
            to_audio.setdefault(key, []).append(uid)
    lost: list[str] = []

    def fix(node: Any) -> Any:
        if isinstance(node, list):
            return [fix(v) for v in node]
        if not isinstance(node, dict):
            return node
        out = {k: fix(v) for k, v in node.items()}
        if "evidence" in node:
            ids: list[str] = []
            for e in node["evidence"]:
                found = to_audio.get(f"{scenario_id}:{e}", [])
                lost.extend([] if found else [f"{scenario_id}:{e}"])
                ids += [i for i in found if i not in ids]
            out["evidence"] = ids
        return out

    return fix(scenario["gemini_draft"]), scenario["entail_not_supported"], lost


def run_checks(
    scenario_id: str, utterances: list[Utterance], mapping: dict[str, list[str]]
) -> dict:
    """付け替えた見本の下書きで build_draft の照合までを通す（Gemini は呼ばない）。

    2場面をつないだ録音（r3）では、その場面に当たる発言だけを会話として照合する。
    """
    mine = [u for u in utterances if any(k.startswith(f"{scenario_id}:") for k in mapping[u.id])]
    draft, not_supported, lost = remap_draft(scenario_id, mapping)
    scenario = next(s for s in load_scenarios() if s["id"] == scenario_id)
    roster = load_patients()
    mock = MockGemini(
        [{"id": "audio", "gemini_draft": draft, "entail_not_supported": not_supported}],
        draft_scenario_id="audio",
    )
    response = build_draft(
        mode="live",
        patient=next(p for p in roster if p.id == scenario["patient_id"]),
        roster=roster,
        utterances=mine,
        input_kind="audio",
        gemini=mock,
        sealer=EntailSealer(secrets.token_bytes(32)),
    )
    return {
        "scenario": scenario_id,
        "lost_evidence": lost,
        "patient_match": response.patient_match.model_dump(),
        "checks": [c.model_dump() for c in response.checks],
        "missing": response.missing,
        "draft": response.draft.model_dump(),
    }


# ---- 表示 ----


def _print_summary(result: dict) -> None:
    print(f"\n== {result['recording']}（{result['location']} / {result['model']}）==")
    print(
        f"音声 {result['audio_seconds']}秒・{result['audio_bytes']}バイト・認識 {result['calls']}回"
    )
    for raw in result["raw"]:
        print(
            f"  区切り{raw['piece']}（{raw['start']:.1f}〜{raw['end']:.1f}秒）:"
            f" 語 {raw['words']}個、話者ラベル {raw['labels']}"
        )
    print(f"  {result['seconds_taken']}秒かかった")
    print("\n発言の列（[台本の対応] 話者 開始-終了 本文）:")
    for u in result["utterances"]:
        keys = ",".join(result["mapping"][u["id"]]) or "対応なし"
        print(f"  {u['id']:>4} [{keys}] {u['speaker']:<7} {u['start']}-{u['end']} {u['text']}")
    sp = result["speakers"]
    print(f"\n話者の当たり {sp['accuracy']}（入れ替えると {sp['accuracy_if_swapped']}）")
    print(f"  不明 {sp['unknown']}  看護師と患者が混ざった発言 {sp['mixed_speakers']}")
    print("数:")
    for n in result["numbers"]:
        print(
            f"  {'○' if n['ok'] else '×'} {n['script']} 台本 {n['want']} 音声 {n['got']} {n['audio']}"
        )
    for checks in result["checks"]:
        match = checks["patient_match"]
        print(
            f"照合（{checks['scenario']}）: 患者 {match['room']}/{match['name']}"
            f"  抜け {checks['missing']}  根拠の対応なし {checks['lost_evidence']}"
        )
        for c in checks["checks"]:
            print(f"  {c['level']:<5} {c['path']} {c['code']} {c['message']}")
    print(f"文字の一致率（台本との比） {result['char_ratio']}")


def _outside_repo(path: Path) -> bool:
    return REPO_DIR.resolve() not in path.resolve().parents and path.resolve() != REPO_DIR.resolve()


def probe(project: str, locations: list[str]) -> None:
    """リージョンごとに、ja-JP で使えるモデルと機能を表示する（無料の読み取り）。"""
    from google.api_core.client_options import ClientOptions
    from google.cloud.location import locations_pb2
    from google.cloud.speech_v2 import SpeechClient
    from google.cloud.speech_v2.types import LocationsMetadata

    for loc in locations:
        client = SpeechClient(
            client_options=ClientOptions(api_endpoint=f"{loc}-speech.googleapis.com")
        )
        got = client.get_location(
            locations_pb2.GetLocationRequest(name=f"projects/{project}/locations/{loc}")
        )
        ja = LocationsMetadata.deserialize(got.metadata.value).languages.models.get("ja-JP")
        if ja is None:
            print(f"{loc}: ja-JP なし")
            continue
        for model, features in ja.model_features.items():
            names = [f.feature for f in features.model_feature]
            print(f"{loc} {model}: {', '.join(names)}")


def main() -> None:
    """1つの録音を認識し、発言の列・話者・数・照合の結果を JSON と表で出す。"""
    parser = argparse.ArgumentParser()
    parser.add_argument("--project", default="df-2026-t172")
    parser.add_argument("--location", default="us")
    parser.add_argument("--model", default="chirp_3")
    parser.add_argument("--recording", choices=sorted(RECORDINGS))
    parser.add_argument("--audio", type=Path, help="録音のファイル（リポジトリの外）")
    parser.add_argument("--out", type=Path, help="結果を書くフォルダ（リポジトリの外）")
    parser.add_argument("--max-calls", type=int, default=MAX_CALLS, help="承認を取った認識の回数")
    parser.add_argument("--no-diarization", action="store_true", help="話者分離を付けずに送る")
    parser.add_argument("--dry-run", action="store_true", help="認識を呼ばず、台本で流れだけ見る")
    parser.add_argument("--probe", action="store_true", help="使えるモデルと機能を見る（無料）")
    args = parser.parse_args()

    if args.probe:
        probe(args.project, ["asia-northeast1", "us", "eu"])
        return
    if not args.recording or not args.out:
        parser.error("--recording と --out が要る")
    if not _outside_repo(args.out) or (args.audio and not _outside_repo(args.audio)):
        sys.exit("音声と結果はリポジトリの外に置く（P-01）")
    lines = script_lines(args.recording)

    started = time.perf_counter()
    if args.dry_run:
        words, raws, seconds, size = dry_run_words(lines), [], None, 0
    else:
        if args.audio is None:
            parser.error("--audio が要る（費用をかけないなら --dry-run）")
        size = args.audio.stat().st_size
        if size > MAX_AUDIO_BYTES:
            sys.exit("10MB を超える（SEC-04）")
        speech = GoogleSpeech(
            args.project, args.location, args.model, diarization=not args.no_diarization
        )
        words, raws, seconds = recognize(speech, args.audio.read_bytes(), args.max_calls)

    utterances = utterances_from_words(words)
    mapping = align(utterances, lines)
    joined = "".join(_normalize(u.text) for u in utterances)
    script = "".join(_normalize(line.text) for line in lines)
    result = {
        "recording": args.recording,
        "location": args.location,
        "model": args.model,
        "dry_run": args.dry_run,
        "audio_seconds": round(seconds, 1) if seconds else None,
        "audio_bytes": size,
        "calls": len(raws),
        "seconds_taken": round(time.perf_counter() - started, 1),
        "raw": raws,
        "utterances": [u.model_dump() for u in utterances],
        "mapping": mapping,
        "speakers": speaker_report(utterances, mapping, lines),
        "numbers": number_report(utterances, mapping, lines),
        "char_ratio": round(difflib.SequenceMatcher(None, joined, script).ratio(), 3),
        "checks": [
            run_checks(scenario_id, utterances, mapping)
            for scenario_id, _ in RECORDINGS[args.recording]
            if utterances
        ],
    }
    args.out.mkdir(parents=True, exist_ok=True)
    name = f"{args.recording}_{args.location}_{args.model}"
    name += "_nodiar" * args.no_diarization
    (args.out / f"{name}{'_dry' if args.dry_run else ''}.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    if utterances:
        _print_summary(result)
    else:
        print("発言が1つも取れなかった:", json.dumps(raws, ensure_ascii=False)[:2000])


if __name__ == "__main__":
    main()
