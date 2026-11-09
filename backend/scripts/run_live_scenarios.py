"""技術検証（段階 A）：利用シーン5場面を本物の Gemini に通し、合否と費用を見る。

**費用がかかる。実行の前にCさんの承認を取る。** 呼び出しは場面ごとに ① 下書き ②
二段目の2回（5場面で10回）。認証は ADC（`gcloud auth application-default login`）。

使い方（backend/ で）:
    python -m scripts.run_live_scenarios --out 結果を書くフォルダ
    python -m scripts.run_live_scenarios --location us-central1 --out ...
"""

import argparse
import json
import logging
import secrets
import time
from pathlib import Path

from app.live.gemini_vertex import VertexGemini
from app.models.draft import Utterance
from app.services.drafting import build_draft
from app.services.entail_seal import EntailSealer
from app.services.mock_data import load_patients, load_scenarios
from tests.scenario_eval import evaluate

MAX_CALLS = 10  # 承認を取った回数。これを超える前に止める


class _UsageCollector(logging.Handler):
    """gemini_usage のログを集める（トークン数・費用・秒）。"""

    def __init__(self) -> None:
        super().__init__()
        self.entries: list[dict] = []

    def emit(self, record: logging.LogRecord) -> None:
        try:
            entry = json.loads(record.getMessage())
        except ValueError:
            return
        if entry.get("event") in ("gemini_usage", "entail_failed", "draft_failed"):
            self.entries.append(entry)


def main() -> None:
    """全場面を1回ずつ回し、結果を JSON と表で出す。"""
    parser = argparse.ArgumentParser()
    parser.add_argument("--project", default="df-2026-t172")
    parser.add_argument("--location", default="global")
    parser.add_argument("--model", default="gemini-3.5-flash")
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--scenarios", nargs="+", help="回す場面（例: s1 s2）。省くと全場面")
    parser.add_argument(
        "--max-calls", type=int, default=MAX_CALLS, help="承認を取った呼び出しの回数"
    )
    args = parser.parse_args()

    collector = _UsageCollector()
    logging.getLogger("app").addHandler(collector)
    logging.getLogger("app").setLevel(logging.INFO)
    gemini = VertexGemini(args.project, args.location, args.model)
    roster = load_patients()
    sealer = EntailSealer(secrets.token_bytes(32))
    args.out.mkdir(parents=True, exist_ok=True)
    summary = []
    scenarios = [s for s in load_scenarios() if not args.scenarios or s["id"] in args.scenarios]
    for scenario in scenarios:
        if sum(e["event"] == "gemini_usage" for e in collector.entries) + 2 > args.max_calls:
            print("承認した回数に達したので止める")
            break
        before = len(collector.entries)
        started = time.perf_counter()
        response = build_draft(
            mode="live",
            patient=next(p for p in roster if p.id == scenario["patient_id"]),
            roster=roster,
            utterances=[Utterance.model_validate(u) for u in scenario["utterances"]],
            input_kind="text",
            gemini=gemini,
            sealer=sealer,
        )
        usage = collector.entries[before:]
        problems = evaluate(response.draft, scenario["id"])
        result = {
            "scenario": scenario["id"],
            "title": scenario["title"],
            "passed": not problems,
            "problems": problems,
            "checks": [c.model_dump() for c in response.checks],
            "missing": response.missing,
            "usage": usage,
            "seconds": round(time.perf_counter() - started, 1),
            "draft": response.draft.model_dump(),
        }
        summary.append(result)
        (args.out / f"{scenario['id']}.json").write_text(
            json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        usd = sum(e.get("usd", 0) for e in usage)
        thoughts = sum(e.get("thoughts_tokens", 0) for e in usage)
        print(
            f"[{scenario['id']} {scenario['title']}] {'合格' if not problems else '不合格'}"
            f"  止めた{sum(c.level == 'stop' for c in response.checks)}件"
            f"  ${usd:.5f}  思考トークン{thoughts}  {result['seconds']}秒"
        )
        for p in problems:
            print("   -", p)
    total = sum(e.get("usd", 0) for r in summary for e in r["usage"])
    calls = sum(e["event"] == "gemini_usage" for r in summary for e in r["usage"])
    print(f"\n呼び出し {calls}回、費用の合計 ${total:.5f}（約{total * 150:.2f}円）")


if __name__ == "__main__":
    main()
