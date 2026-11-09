"""モードに応じて、保存先と外のサービスの呼び口を組み立てる。

MODE=mock では Gemini・Speech-to-Text・Firestore を一切呼ばない（data-model.md の 5章）。
テストでは build_services を使わず、Services を直接作って差し替える。
"""

from dataclasses import dataclass, field

from app.config import Settings
from app.live.interfaces import GeminiClient, SpeechClient
from app.live.mock_gemini import MockGemini
from app.models.api import Patient
from app.models.nurse import Nurse
from app.services.call_limit import DailyCallLimit
from app.services.clock import now_jst
from app.services.draft_token import DraftTokenSigner
from app.services.entail_seal import EntailSealer
from app.services.mock_data import load_demo_tasks, load_nurses, load_patients, load_scenarios
from app.services.safe_log import log_failure
from app.store.base import Store
from app.store.memory import MemoryStore


@dataclass
class Services:
    """API が使う部品一式。speech は mock では None（音声は場面の見本で代える）。

    roster は起動時に1回読んだ名簿（架空。下書きのたびに Firestore を読まないため）。
    nurses は架空の看護師の一覧（S-08）。名簿と同じく起動時に読み、保存先には入れない。
    """

    store: Store
    gemini: GeminiClient
    speech: SpeechClient | None
    call_limit: DailyCallLimit
    sealer: EntailSealer
    draft_tokens: DraftTokenSigner
    roster: list[Patient]
    nurses: list[Nurse] = field(default_factory=load_nurses)


def build_services(settings: Settings) -> Services:
    """設定のモードに応じて部品を作る。live でも、作った時点では通信しない。"""
    call_limit = DailyCallLimit(settings.daily_call_limit, settings.daily_call_limit_per_client)
    sealer = EntailSealer(settings.seal_key)
    draft_tokens = DraftTokenSigner(settings.seal_key)
    roster = load_patients()
    if settings.mode == "mock":
        store = MemoryStore(roster, load_demo_tasks(now_jst()))
        gemini = MockGemini(list(load_scenarios()))
        return Services(store, gemini, None, call_limit, sealer, draft_tokens, roster)

    from app.live.gemini_vertex import VertexGemini
    from app.live.speech_v2 import GoogleSpeech
    from app.store.firestore_store import FirestoreStore

    return Services(
        store=FirestoreStore.connect(settings.project, settings.firestore_database),
        gemini=VertexGemini(settings.project, settings.gemini_location, settings.gemini_model),
        speech=GoogleSpeech(settings.project, settings.speech_location, settings.speech_model),
        call_limit=call_limit,
        sealer=sealer,
        draft_tokens=draft_tokens,
        roster=roster,
    )


def seed_patients(services: Services) -> None:
    """live のとき、起動時に架空の名簿を Firestore に入れる。

    失敗しても起動は止めない（提出後は人が再起動できないため。名簿は前回の分が残る）。
    """
    seed = getattr(services.store, "seed_patients", None)
    if seed is None:
        return
    try:
        seed(services.roster)
    except Exception as e:
        log_failure("seed_patients_failed", e)
