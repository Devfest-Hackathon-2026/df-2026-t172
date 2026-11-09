"""テストの共通部品。外のサービスは一切呼ばない。"""

import copy
import uuid
from pathlib import Path
from typing import Any

from app.config import Settings
from app.container import Services
from app.live.mock_gemini import MockGemini
from app.models.api import Patient
from app.models.draft import Draft, Utterance
from app.models.gemini import GeminiDraft
from app.services.call_limit import DailyCallLimit
from app.services.clock import now_jst
from app.services.draft_token import DraftTokenSigner
from app.services.entail_seal import EntailSealer
from app.services.mock_data import load_demo_tasks, load_patients, load_scenarios
from app.services.soap import to_soap
from app.store.memory import MemoryStore

PASSCODE = "test-passcode"
HEADERS = {"X-Passcode": PASSCODE}

SCENARIOS: dict[str, dict[str, Any]] = {sc["id"]: sc for sc in load_scenarios()}
ROSTER: list[Patient] = load_patients()


def utterances_of(scenario_id: str) -> list[Utterance]:
    """場面の発言の列。"""
    return [Utterance.model_validate(u) for u in SCENARIOS[scenario_id]["utterances"]]


def gemini_draft_of(scenario_id: str, mutate: Any = None) -> GeminiDraft:
    """場面の下書きの見本（Gemini の形）。mutate で dict のまま壊せる。"""
    data = copy.deepcopy(SCENARIOS[scenario_id]["gemini_draft"])
    if mutate:
        mutate(data)
    return GeminiDraft.model_validate(data)


def draft_of(scenario_id: str, mutate: Any = None) -> Draft:
    """場面の下書きの見本（SOAP の形）。"""
    return to_soap(gemini_draft_of(scenario_id, mutate))


def make_settings(mode: str = "mock", **overrides: Any) -> Settings:
    """テスト用の設定。"""
    values: dict[str, Any] = {
        "mode": mode,
        "passcode": PASSCODE,
        "project": "test-project",
        "gemini_location": "global",
        "gemini_model": "gemini-3.5-flash",
        "speech_location": "asia-northeast1",
        "speech_model": "chirp_3",
        "firestore_database": "(default)",
        "daily_call_limit": 100,
        "daily_call_limit_per_client": 100,
        "max_json_bytes": 1024 * 1024,
        "max_audio_bytes": 1024,
        "max_audio_seconds": 180.0,
        "max_transcript_chars": 5000,
        "frontend_dir": Path("does-not-exist"),
        "seal_key": b"test-seal-key",
    }
    values.update(overrides)
    return Settings(**values)


def make_services(
    gemini: Any = None, speech: Any = None, limit: int = 100, per_client: int = 100
) -> Services:
    """メモリの保存先と差し替えの呼び口で、部品一式を作る。"""
    return Services(
        store=MemoryStore(load_patients(), load_demo_tasks(now_jst())),
        gemini=gemini or MockGemini(list(load_scenarios())),
        speech=speech,
        call_limit=DailyCallLimit(limit, per_client),
        sealer=EntailSealer(b"test-seal-key"),
        draft_tokens=DraftTokenSigner(b"test-seal-key"),
        roster=load_patients(),
    )


def post_text_draft(client: Any, patient_id: str, transcript: str = "看護師: こんにちは") -> dict:
    """テキストで下書きを作り、応答の JSON を返す。"""
    body = {"patient_id": patient_id, "transcript": transcript}
    res = client.post("/api/drafts", json=body, headers=HEADERS)
    assert res.status_code == 200, res.text
    return res.json()


def record_body(draft: dict[str, Any], **overrides: Any) -> dict[str, Any]:
    """下書きの応答を、そのまま確定の入力にする。"""
    body = {
        "confirm_id": f"c_{uuid.uuid4().hex[:12]}",
        "patient_id": draft["patient"]["id"],
        "utterances": draft["utterances"],
        "draft": draft["draft"],
        "entail_seals": draft["entail_seals"],
        "draft_token": draft["draft_token"],
        "decisions": [],
        "timing": {"recording_started": "2026-11-08T09:10:00+09:00"},
    }
    body.update(overrides)
    return body
