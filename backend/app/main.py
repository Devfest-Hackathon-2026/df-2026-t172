"""FastAPI のアプリ。API と画面の静的ファイル（frontend/）を1つのコンテナで配信する。

起動: `PASSCODE=... MODE=mock uvicorn --factory app.main:create_app`（backend/ で実行）
`--factory` にしているのは、import しただけでは環境変数を読まないようにするため（テストで設定を差し替える）。
"""

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI
from fastapi.staticfiles import StaticFiles
from starlette.types import ASGIApp

from app.auth import authenticate
from app.config import Settings, load_settings
from app.container import Services, build_services, seed_patients
from app.errors import install_error_handlers
from app.middleware.body_limit import BodyLimit
from app.middleware.error_guard import ErrorGuard
from app.routes import drafts, nurses, patients, record_views, records, tasks, verify

logging.basicConfig(level=logging.INFO, format="%(message)s")


class GuardedFastAPI(FastAPI):
    """いちばん外側（Starlette の ServerErrorMiddleware のさらに外）を ErrorGuard で包む。"""

    def build_middleware_stack(self) -> ASGIApp:
        """FastAPI が組んだミドルウェアの列を、ErrorGuard で包んで返す。"""
        return ErrorGuard(super().build_middleware_stack(), self.state.settings.mode)


def create_app(settings: Settings | None = None, services: Services | None = None) -> FastAPI:
    """アプリを作る。テストでは settings と services を差し替える。"""
    cfg = settings or load_settings()
    svc = services or build_services(cfg)

    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        seed_patients(svc)
        yield

    # 公開 URL で API の一覧（/docs など）を見せない
    app = GuardedFastAPI(
        title="看護記録の下書き", lifespan=lifespan, docs_url=None, redoc_url=None, openapi_url=None
    )
    app.state.settings, app.state.services = cfg, svc
    install_error_handlers(app)
    app.add_middleware(
        BodyLimit,
        mode=cfg.mode,
        max_json_bytes=cfg.max_json_bytes,
        max_audio_bytes=cfg.max_audio_bytes,
    )

    for module in (patients, nurses, drafts, verify, records, record_views, tasks):
        app.include_router(module.router, dependencies=[Depends(authenticate)])

    # /healthz は Cloud Run が予約していて届かないので、/api の下に置く
    @app.get("/api/health")
    def health() -> dict[str, str]:
        """動いているかの確認（合言葉なし。患者の情報は返さない）。"""
        return {"mode": cfg.mode, "status": "ok"}

    # API より後に置く（/api を画面のファイルで隠さないため）
    if cfg.frontend_dir.is_dir():
        app.mount("/", StaticFiles(directory=cfg.frontend_dir, html=True), name="frontend")
    return app
