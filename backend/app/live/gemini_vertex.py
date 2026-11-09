"""Gemini（Vertex AI、既定は gemini-3.5-flash）の呼び出し。

- 構造化出力（JSON の形を指定）で返させる
- 思考モードは thinking_level をモデルの最小にする（3系は完全には止められず、
  thinking_budget は非推奨）。思考トークンを毎回数え、費用に足して警告する
  （思考トークンは出力の単価で課金される）
- 認証は Cloud Run のサービスアカウント（Application Default Credentials）
- 1回の呼び出しは TIMEOUT_SECONDS で打ち切る。429・503・JSON の形の崩れは1回だけ
  再試行する（`app.live.gemini_retry`）
"""

import time
from collections.abc import Callable
from typing import Any, TypeVar

from pydantic import BaseModel

from app.checks.conversation import Conversation
from app.checks.entail import ENTAIL_PROMPT, EntailTarget, build_entail_input
from app.live.gemini_retry import call_with_retry
from app.models.draft import Utterance
from app.models.gemini import GeminiDraft, Verdicts
from app.services.safe_log import log_event

M = TypeVar("M", bound=BaseModel)

# モデルごとの料金（global の標準単価。100万トークンあたりのドル）と、指定できる最小の思考の段階。
# Vertex AI の公式の料金ページと思考の説明で 2026-11-07 に確認（ADR-0004）。
# 表にないモデルは費用を出せないので使わない
MODELS: dict[str, tuple[float, float, str]] = {
    "gemini-3.5-flash": (1.50, 9.00, "MINIMAL"),
    "gemini-3.5-flash-lite": (0.30, 2.50, "MINIMAL"),
}
# global 以外（us・eu など）は単価が1割高い
NON_GLOBAL_PRICE_RATE = 1.1
# 1回の呼び出しの上限。下書き（3分の会話）でもふだんは十数秒で返る
TIMEOUT_SECONDS = 30

DRAFT_PROMPT = """あなたは病棟看護師の記録づくりを手伝う。看護師と患者の会話（発言番号つき）から、看護記録の下書きを作る。
守ること:
- 会話に出たことだけを書く。会話にない推測・診断・医療的な判断・今後の方針は書かない
- 会話には雑談（家族、趣味、天気、他の患者の話）が多い。雑談は記録に書かない。ただし雑談の中に出た症状や体の訴えは必ず拾う
- 家族の面会の予定・見舞いの話など、体の具合や看護に関係しない予定の話も雑談で、S にも O にも書かない。体の訴え（だるい・痛い・ふらつくなど）は、雑談の中にあっても拾う
- すべての要素の evidence に、根拠の発言番号を3つまで入れる。根拠がなければ evidence を空にする
- バイタルの value は発言に出た数字にする（血圧は「132/78」の形）。言い直しがあれば後の値にする。同じ項目は1つだけ
- narrative の source は、患者が言ったことなら patient、看護師が観察・測定したことなら nurse。根拠もその話者の発言にする。話者が違う内容は別の文に分ける
- requests は患者からの依頼だけ（根拠は患者の発言）。その場で答え終わった質問は入れない
- 時刻・食事・検査など予定に結びついた患者の希望（「〜が来たら〜したい」など）も requests に入れ、その時刻や予定を cue（時間指定）にする（例: 「検査から戻ったらシャワーを浴びたい」→ cue は「検査のあと」）。根拠は患者の発言にする
- cue は時間指定か、患者が急ぎと言った場合だけ。優先度（至急・優先など）は書かない。「患者が急ぎと言った」の根拠は患者の発言にする
- 薬の名前・量・回数は、narrative・requests・cue・doctor_questions のどこにも書かず、manual_needed に「薬の話あり」として入れる
- 患者に関する医師への確認事項は doctor_questions に入れる
- requests の category（中身の種類）と role（対応する職種）は、決められた一覧から1つずつ選ぶ。ラベルは仕分けのためで、優先度ではない。迷ったら「その他」にする
"""


def format_utterances(utterances: list[Utterance]) -> str:
    """Gemini に渡す発言の列（番号・話者・文）。時刻は渡さない。"""
    return "\n".join(f"{u.id} [{u.speaker}] {u.text}" for u in utterances)


class VertexGemini:
    """Vertex AI の Gemini。client はテストで差し替えられる。"""

    def __init__(
        self,
        project: str,
        location: str,
        model: str,
        client: Any = None,
        sleep: Callable[[float], None] = time.sleep,
    ):
        """client を渡さなければ、最初の呼び出しのときに本物を作る。sleep は再試行の前の待ち。"""
        if model not in MODELS:
            raise ValueError(f"料金を確かめていないモデル: {model}（MODELS に足してから使う）")
        self._project, self._location, self._model = project, location, model
        self._client, self._sleep = client, sleep
        price_in, price_out, self._thinking_level = MODELS[model]
        rate = 1.0 if location == "global" else NON_GLOBAL_PRICE_RATE
        self._prices = (price_in * rate, price_out * rate)

    def _genai_client(self) -> Any:
        if self._client is None:
            from google import genai

            self._client = genai.Client(
                vertexai=True, project=self._project, location=self._location
            )
        return self._client

    def _call(
        self, purpose: str, contents: str, system: str, schema: type[M], temperature: float
    ) -> M:
        """構造化出力で呼ぶ（再試行は1回まで）。"""
        return call_with_retry(
            lambda: self._call_once(purpose, contents, system, schema, temperature),
            purpose=purpose,
            model=self._model,
            sleep=self._sleep,
        )

    def _call_once(
        self, purpose: str, contents: str, system: str, schema: type[M], temperature: float
    ) -> M:
        """構造化出力で1回呼び、使用量をログに出す。"""
        from google.genai import types

        started = time.perf_counter()
        response = self._genai_client().models.generate_content(
            model=self._model,
            contents=contents,
            config=types.GenerateContentConfig(
                system_instruction=system,
                response_mime_type="application/json",
                response_schema=schema,
                temperature=temperature,
                thinking_config=types.ThinkingConfig(thinking_level=self._thinking_level),
                http_options=types.HttpOptions(timeout=TIMEOUT_SECONDS * 1000),  # ミリ秒
            ),
        )
        _log_usage(purpose, response.usage_metadata, self._prices, time.perf_counter() - started)
        return schema.model_validate_json(response.text)

    def generate_draft(self, utterances: list[Utterance]) -> GeminiDraft:
        """① 発言の列から下書きを作る。"""
        return self._call("draft", format_utterances(utterances), DRAFT_PROMPT, GeminiDraft, 0.0)

    def judge(self, targets: list[EntailTarget], utterances: list[Utterance]) -> Verdicts:
        """② 各文が根拠の発言だけから言えるかを判定する。"""
        contents = build_entail_input(targets, Conversation.of(utterances))
        return self._call("entail", contents, ENTAIL_PROMPT, Verdicts, 0.0)


def _log_usage(purpose: str, usage: Any, prices: tuple[float, float], seconds: float) -> None:
    """トークン数と費用を構造化ログで出す。思考トークンも出力として数える。"""
    tokens_in = usage.prompt_token_count or 0
    tokens_out = usage.candidates_token_count or 0
    thoughts = usage.thoughts_token_count or 0
    price_in, price_out = prices
    usd = (tokens_in * price_in + (tokens_out + thoughts) * price_out) / 1e6
    warning = {"message": "思考トークンが出ている。thinking_level を確認する"} if thoughts else {}
    log_event(
        "gemini_usage",
        severity="WARNING" if thoughts else "INFO",
        purpose=purpose,
        input_tokens=tokens_in,
        output_tokens=tokens_out,
        thoughts_tokens=thoughts,
        usd=round(usd, 6),
        seconds=round(seconds, 2),
        **warning,
    )
