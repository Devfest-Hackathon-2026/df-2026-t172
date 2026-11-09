"""Gemini を呼ばない差し替え（MODE=mock と、モック JSON の作成に使う）。

下書きは、場面ごとに決めた見本（`backend/mock/source/scenarios.json` の
gemini_draft）を返す。二段目の確認は、見本の文なら決めた判定を返し、看護師が
直した文など見本にない文は「判断できない」を返す（黙って通さない）。
"""

from typing import Any

from app.checks.entail import EntailTarget, entail_targets
from app.models.draft import Utterance
from app.models.gemini import GeminiDraft, Verdict, Verdicts
from app.services.soap import to_soap

UNKNOWN_SENTENCE_REASON = "モックでは二段目を呼ばないため、見本にない文は判断できない"


class MockGemini:
    """見本の下書きと、見本の二段目の判定を返す。"""

    def __init__(self, scenarios: list[dict[str, Any]], draft_scenario_id: str | None = None):
        """見本の場面の一覧で作る。draft_scenario_id は generate_draft で返す場面。"""
        self._drafts = {
            sc["id"]: GeminiDraft.model_validate(sc["gemini_draft"]) for sc in scenarios
        }
        self._draft_scenario_id = draft_scenario_id
        self._not_supported: dict[str, str] = {}
        self._known_texts: set[str] = set()
        for sc in scenarios:
            self._not_supported.update(sc["entail_not_supported"])
            targets = entail_targets(to_soap(self._drafts[sc["id"]]))
            self._known_texts |= {t.text for t in targets}

    def generate_draft(self, utterances: list[Utterance]) -> GeminiDraft:
        """決めた場面の見本の下書きを返す（会話の中身は見ない）。

        Raises:
            ValueError: 返す場面が決まっていない場合
        """
        if self._draft_scenario_id is None:
            raise ValueError("モックで返す場面が決まっていない")
        return self._drafts[self._draft_scenario_id].model_copy(deep=True)

    def judge(self, targets: list[EntailTarget], utterances: list[Utterance]) -> Verdicts:
        """見本の判定を返す。見本にない文は unclear。"""
        items = []
        for i, target in enumerate(targets):
            if target.text in self._not_supported:
                verdict = Verdict(
                    index=i, verdict="not_supported", reason=self._not_supported[target.text]
                )
            elif target.text in self._known_texts:
                verdict = Verdict(index=i, verdict="supported", reason="（モックの見本）")
            else:
                verdict = Verdict(index=i, verdict="unclear", reason=UNKNOWN_SENTENCE_REASON)
            items.append(verdict)
        return Verdicts(items=items)
