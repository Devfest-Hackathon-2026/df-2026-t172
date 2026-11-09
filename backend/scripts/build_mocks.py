"""モック JSON（backend/mock/draft_s1.json〜draft_s5.json）を作り直す。

元データ（backend/mock/source/scenarios.json）の下書きの見本を、本物と同じ照合
（コード）と、見本の二段目の判定に通して書き出す。照合を直したら、これを回して
モック JSON を作り直す（tests/test_mock_files.py が食い違いを見つける）。

使い方（backend/ で）: python -m scripts.build_mocks
"""

import json

from app.live.mock_gemini import MockGemini
from app.models.api import DraftResponse
from app.models.draft import Utterance
from app.services.drafting import build_draft
from app.services.entail_seal import EntailSealer
from app.services.mock_data import load_patients, load_scenarios, mock_draft_path


def build_mock(scenario_id: str) -> DraftResponse:
    """1場面のモックの応答を作る。

    二段目の署名は鍵が起動ごとに変わるので入れない（API が返すときにその場で付ける）。
    """
    scenarios = list(load_scenarios())
    scenario = next(sc for sc in scenarios if sc["id"] == scenario_id)
    roster = load_patients()
    patient = next(p for p in roster if p.id == scenario["patient_id"])
    return build_draft(
        mode="mock",
        patient=patient,
        roster=roster,
        utterances=[Utterance.model_validate(u) for u in scenario["utterances"]],
        input_kind="audio",
        gemini=MockGemini(scenarios, draft_scenario_id=scenario_id),
        sealer=EntailSealer(b"unused"),
    ).model_copy(update={"entail_seals": [], "draft_token": ""})


def main() -> None:
    """全場面のモック JSON を書き出す。"""
    for scenario in load_scenarios():
        response = build_mock(scenario["id"])
        path = mock_draft_path(scenario["id"])
        text = json.dumps(response.model_dump(mode="json"), ensure_ascii=False, indent=2)
        path.write_text(text + "\n", encoding="utf-8")
        print(f"{path.name}: checks {len(response.checks)}件、抜け {response.missing}")


if __name__ == "__main__":
    main()
