"""live の接続コード（Gemini・Speech-to-Text・Firestore）を、差し替えで確かめる。"""

import json
import logging
from datetime import timedelta
from types import SimpleNamespace as NS
from typing import Any

import pytest

from app.checks.entail import entail_targets
from app.live.gemini_vertex import VertexGemini
from app.live.speech_v2 import words_of
from app.services.clock import now_jst
from app.services.utterances import Word, utterances_from_words
from app.store.firestore_store import FirestoreStore
from tests.helpers import ROSTER, SCENARIOS, draft_of, utterances_of


class FakeModels:
    def __init__(self, text: str, thoughts: int = 0):
        self.text, self.thoughts = text, thoughts
        self.kwargs: dict[str, Any] = {}

    def generate_content(self, **kwargs: Any) -> Any:
        self.kwargs = kwargs
        usage = NS(
            prompt_token_count=1000, candidates_token_count=200, thoughts_token_count=self.thoughts
        )
        return NS(text=self.text, usage_metadata=usage)


def _gemini(text: str, thoughts: int = 0) -> tuple[VertexGemini, FakeModels]:
    models = FakeModels(text, thoughts)
    return VertexGemini("p", "global", "gemini-3.5-flash", client=NS(models=models)), models


def test_C03_generate_draft_config(caplog: pytest.LogCaptureFixture) -> None:
    gemini, models = _gemini(json.dumps(SCENARIOS["s1"]["gemini_draft"]))
    with caplog.at_level(logging.INFO):
        draft = gemini.generate_draft(utterances_of("s1"))
    assert draft.vitals[0].value == "36.8"
    config = models.kwargs["config"]
    assert config.thinking_config.thinking_level == "MINIMAL"
    assert config.thinking_config.thinking_budget is None
    assert config.response_mime_type == "application/json"
    assert models.kwargs["contents"].startswith("u1 [nurse] ")
    usage = json.loads(caplog.records[-1].message)
    assert usage["thoughts_tokens"] == 0 and usage["usd"] == pytest.approx(
        (1000 * 1.50 + 200 * 9.00) / 1e6
    )


def test_C03_thought_tokens_are_counted_and_warned(caplog: pytest.LogCaptureFixture) -> None:
    gemini, _ = _gemini(json.dumps({"items": []}), thoughts=400)
    with caplog.at_level(logging.INFO):
        gemini.judge(entail_targets(draft_of("s1")), utterances_of("s1"))
    usage = json.loads(caplog.records[-1].message)
    assert usage["severity"] == "WARNING"
    assert usage["usd"] == pytest.approx((1000 * 1.50 + 600 * 9.00) / 1e6)


def test_C03_unpriced_model_is_rejected() -> None:
    with pytest.raises(ValueError, match="料金を確かめていない"):
        VertexGemini("p", "global", "gemini-2.5-flash")


def test_C03_non_global_costs_more() -> None:
    gemini = VertexGemini("p", "us", "gemini-3.5-flash-lite")
    assert gemini._prices == pytest.approx((0.33, 2.75))


def test_judge_input_has_evidence_and_question_context() -> None:
    gemini, models = _gemini(json.dumps({"items": []}))
    gemini.judge(entail_targets(draft_of("s1")), utterances_of("s1"))
    contents = models.kwargs["contents"]
    assert "[0] 文: 夜間に創部痛あり" in contents
    assert "u9[患者]「傷がさ、夜中ちょっとズキズキして" in contents
    assert "前の質問: u10「そうでしたか。痛みは10段階で" in contents


def test_utterances_from_diarized_words() -> None:
    words = [
        Word("302号室の", 0.0, 0.8, "1"), Word("田中さん", 0.8, 1.4, "1"),
        Word("はい", 1.6, 2.0, "2"), Word("36.8度です", 2.2, 3.0, "1"),
        Word("それと", 6.0, 6.4, "1"), Word("こんにちは", 7.0, 7.5, "3"),
    ]  # fmt: skip
    got = [(u.id, u.speaker, u.start, u.end, u.text) for u in utterances_from_words(words)]
    assert got == [
        ("u1", "nurse", 0.0, 1.4, "302号室の田中さん"),
        ("u2", "patient", 1.6, 2.0, "はい"),
        ("u3", "nurse", 2.2, 3.0, "36.8度です"),
        ("u4", "nurse", 6.0, 6.4, "それと"),  # 3秒空いたので別の発言
        ("u5", "unknown", 7.0, 7.5, "こんにちは"),
    ]


def test_words_of_falls_back_to_transcript_without_word_offsets() -> None:
    def result(transcript: str, end: float) -> Any:
        alt = NS(words=[], transcript=transcript)
        return NS(alternatives=[alt], result_end_offset=timedelta(seconds=end))

    response = NS(results=[result("こんにちは。", 2.0), result("熱を測りますね。", 4.5)])
    utterances = utterances_from_words(words_of(response))
    assert [(u.speaker, u.start, u.end, u.text) for u in utterances] == [
        ("unknown", 0.0, 2.0, "こんにちは。"),
        ("unknown", 2.0, 4.5, "熱を測りますね。"),
    ]


class FakeDoc:
    def __init__(self, store: dict, key: tuple[str, str]):
        self._store, self._key, self.id = store, key, key[1]

    @property
    def exists(self) -> bool:
        return self._key in self._store

    def get(self) -> "FakeDoc":
        return self

    def to_dict(self) -> dict:
        return dict(self._store[self._key])

    def update(self, fields: dict) -> None:
        self._store[self._key].update(fields)

    def set(self, fields: dict) -> None:
        self._store[self._key] = dict(fields)


class FakeCollection:
    def __init__(self, store: dict, name: str, where: tuple | None = None):
        self._store, self._name, self._where = store, name, where

    def document(self, doc_id: str) -> FakeDoc:
        return FakeDoc(self._store, (self._name, doc_id))

    def where(self, field: str, op: str, value: Any) -> "FakeCollection":
        return FakeCollection(self._store, self._name, (field, value))

    def stream(self) -> list[FakeDoc]:
        keys = [k for k in self._store if k[0] == self._name]
        docs = [FakeDoc(self._store, k) for k in keys]
        if self._where:
            docs = [d for d in docs if d.to_dict()[self._where[0]] == self._where[1]]
        return docs


class FakeFirestore:
    def __init__(self) -> None:
        self.data: dict[tuple[str, str], dict] = {}

    def collection(self, name: str) -> FakeCollection:
        return FakeCollection(self.data, name)

    def batch(self) -> Any:
        pending: list[tuple[FakeDoc, dict]] = []
        return NS(
            set=lambda doc, fields: pending.append((doc, fields)),
            commit=lambda: [self.data.__setitem__(d._key, dict(f)) for d, f in pending],
        )


def test_firestore_store_round_trip() -> None:
    db = FakeFirestore()
    store = FirestoreStore(db)
    store.seed_patients(ROSTER)
    assert [p.id for p in store.list_patients()][:2] == ["p302", "p303"]
    assert store.get_patient("p305").name == "佐藤"  # type: ignore[union-attr]
    now = now_jst()
    task = {"id": "t1", "status": "open", "urgency": "none", "expires_at": now + timedelta(hours=1)}
    old = {**task, "id": "t0", "expires_at": now - timedelta(minutes=1)}
    store.save_record("r1", {"patient_id": "p302", "expires_at": now}, [task, old])
    assert "utterances" not in db.data[("records", "r1")]
    assert [t["id"] for t in store.list_tasks("open", now)] == ["t1"]  # 期限切れは読まない
    assert store.update_task("t1", {"status": "done"}, now)["status"] == "done"  # type: ignore[index]
    assert store.list_tasks("open", now) == []
    assert store.update_task("t0", {"status": "done"}, now) is None
