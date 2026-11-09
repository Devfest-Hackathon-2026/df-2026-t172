"""デプロイしたバックエンドを外から通しで確かめる総合テスト。

提出の直前と、デプロイのたびに回す。画面から API を呼ぶ順の見本にもなる。

    cd backend
    SMOKE_PASSCODE=... .venv/Scripts/python -m scripts.smoke_test --url https://...

- 合言葉は環境変数 `SMOKE_PASSCODE` から読む（引数・出力・ファイルに出さない）
- live の URL では、`--allow-paid` を付けたときだけ `/api/drafts` と `/api/verify`
  （entail=true）を呼ぶ（Gemini を呼ぶのでお金がかかる）。付けなければ飛ばす
- 終了コードは NG の数（0 なら全部 OK）
"""

import argparse
import os
import sys

from scripts.smoke_client import Smoke, error_code
from scripts.smoke_flow import run_flow, scene1

PASSCODE_ENV = "SMOKE_PASSCODE"
MAX_TRANSCRIPT_CHARS = 5000  # backend/app/models/limits.py の MAX_TEXT_CHARS と同じ（SEC-04）


def check_health(smoke: Smoke) -> None:
    """合言葉なしで動いているかを確かめ、mode を覚える。"""
    res = smoke.request("GET", "/api/health", passcode=False)
    if smoke.expect_status("health：合言葉なしで 200", res, 200):
        body = res.json()
        smoke.mode = body.get("mode")
        smoke.check("health：status が ok", body.get("status") == "ok", f"mode={smoke.mode}")


def check_closed_doors(smoke: Smoke) -> None:
    """合言葉がないと 401、API の一覧（/docs など）は 404 かを確かめる（SEC-01）。"""
    res = smoke.request("GET", "/api/patients", passcode=False)
    if smoke.expect_status("合言葉なしで 401", res, 401):
        smoke.check("合言葉なし：code が bad_passcode", error_code(res) == "bad_passcode")
    for path in ("/docs", "/redoc", "/openapi.json"):
        smoke.expect_status(f"{path} が 404", smoke.request("GET", path), 404)


def check_patients(smoke: Smoke) -> None:
    """名簿が部屋番号の順で、受け持ちの欄（assigned_to）があるかを確かめる（S-08）。"""
    res = smoke.request("GET", "/api/patients")
    if not smoke.expect_status("名簿：200", res, 200):
        return
    patients = res.json()["patients"]
    rooms = [p["room"] for p in patients]
    smoke.check("名簿：1人以上いる", len(patients) >= 1, f"{len(patients)}人")
    smoke.check(
        "名簿：部屋番号の順",
        rooms == sorted(rooms, key=lambda r: (len(r), r)),
        f"rooms={rooms}",
    )
    smoke.check("名簿：全員に assigned_to がある", all("assigned_to" in p for p in patients))


def check_input_guards(smoke: Smoke) -> None:
    """お金のかからない入力の止め方を確かめる（Gemini を呼ぶ前に止まる）。

    - O-01：音声で consent_confirmed がないと 400
    - SEC-04：テキストが5,001字だと 413
    """
    patient_id, _ = scene1()
    res = smoke.request(
        "POST",
        "/api/drafts",
        data={"patient_id": patient_id},
        files={"audio": ("smoke.webm", b"\x00" * 16, "audio/webm")},
    )
    if smoke.expect_status("音声：同意の確認がないと 400", res, 400):
        smoke.check("音声：code が consent_required", error_code(res) == "consent_required")

    long_text = "患者: " + "あ" * (MAX_TRANSCRIPT_CHARS + 1 - len("患者: "))
    res = smoke.request(
        "POST", "/api/drafts", json={"patient_id": patient_id, "transcript": long_text}
    )
    if smoke.expect_status("テキスト：5,001字で 413", res, 413):
        smoke.check(
            "テキスト：code が transcript_too_long", error_code(res) == "transcript_too_long"
        )


def run(smoke: Smoke, *, allow_paid: bool) -> bool:
    """全部を順に回す。確定まで呼んだら True。"""
    check_health(smoke)
    check_closed_doors(smoke)
    check_patients(smoke)
    confirmed = False
    if smoke.mode == "mock" or allow_paid:
        confirmed = run_flow(smoke)
    else:
        reason = "live で --allow-paid がない" if smoke.mode == "live" else "mode が分からない"
        smoke.skip("下書き・照合・確定・タスク（Gemini を呼ぶ所）", reason)
    check_input_guards(smoke)
    return confirmed


def parse_args(argv: list[str] | None) -> argparse.Namespace:
    """引数を読む（合言葉は引数で受けない）。"""
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--url", required=True, help="バックエンドの URL（例 http://localhost:8080）"
    )
    parser.add_argument(
        "--allow-paid",
        action="store_true",
        help="live でも Gemini を呼ぶ所（下書き・entail=true）を回す。お金がかかる",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    """総合テストを回し、NG の数を返す。"""
    sys.stdout.reconfigure(encoding="utf-8")
    args = parse_args(argv)
    passcode = os.environ.get(PASSCODE_ENV, "")
    if not passcode:
        print(f"環境変数 {PASSCODE_ENV} に合言葉を入れてください")
        return 2
    print(f"総合テスト：{args.url}")
    smoke = Smoke(args.url, passcode)
    try:
        confirmed = run(smoke, allow_paid=args.allow_paid)
    finally:
        smoke.close()
    print(f"\nOK {smoke.ok_count} / NG {smoke.ng} / 飛ばした {smoke.skipped}（mode={smoke.mode}）")
    if smoke.mode == "live" and confirmed:
        print("確定で書いた記録とタスクは Firestore に残る（翌日0時以降に TTL で消える）")
    return min(smoke.ng, 255)


if __name__ == "__main__":
    sys.exit(main())
