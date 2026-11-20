"""LexLab API — modular monolith entry point."""

from __future__ import annotations

import asyncio
import logging
import shutil
import time
import uuid
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import APIRouter, FastAPI, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from sqlalchemy import text

from app.core.config import SchedulerMode, get_settings
from app.core.context import ClientInfo, set_client, set_request_id
from app.core.errors import register_exception_handlers
from app.core.logging import configure_logging
from app.db.session import dispose_engine, get_engine, init_engine
from app.modules.anchoring.router import router as anchoring_router
from app.modules.assistant.router import router as assistant_router
from app.modules.audit.router import router as audit_router
from app.modules.auth.router import router as auth_router
from app.modules.calc.router import router as calc_router
from app.modules.cases.router import router as cases_router
from app.modules.contracts.router import router as contracts_router
from app.modules.files.router import router as files_router
from app.modules.moderation.router import router as moderation_router
from app.modules.notifications.router import router as notifications_router
from app.modules.obligations.router import router as obligations_router
from app.modules.rules.router import router as rules_router
from app.modules.scan.router import router as scan_router
from app.modules.templates.router import router as templates_router
from app.modules.users.router import admin as admin_users_router
from app.modules.users.router import companies as companies_router
from app.modules.users.router import router as users_router
from app.workers import queue, scheduler


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    s = get_settings()
    configure_logging(s.log_level, s.log_json)
    init_engine()
    stop = asyncio.Event()
    loop_task = None
    if s.scheduler_mode == SchedulerMode.INPROCESS:
        loop_task = asyncio.create_task(scheduler.run_forever(stop), name="scheduler")
    try:
        yield
    finally:
        stop.set()
        if loop_task:
            await loop_task
        await queue.drain(timeout=10)
        await dispose_engine()


def create_app() -> FastAPI:
    s = get_settings()
    app = FastAPI(
        title=s.app_name,
        version="0.1.0",
        description=(
            "Shartnoma platformasi API: «Shartnoma tuz», «Shartnomani tekshir», tasdiqlash, "
            "majburiyatlar va eslatmalar, yurist arxivi."
        ),
        lifespan=lifespan,
        docs_url="/docs" if s.is_dev or s.debug else None,
        redoc_url=None,
        openapi_url="/openapi.json" if s.is_dev or s.debug else None,
    )
    app.add_middleware(
        CORSMiddleware,
        allow_origins=s.cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
        expose_headers=["X-Request-ID", "X-Content-SHA256"],
    )

    @app.middleware("http")
    async def request_context(request: Request, call_next: Callable[[Request], Awaitable[Response]]) -> Response:
        rid = request.headers.get("X-Request-ID") or uuid.uuid4().hex
        set_request_id(rid[:64])
        fwd = request.headers.get("X-Forwarded-For")
        ip = fwd.split(",")[0].strip() if fwd else (request.client.host if request.client else None)
        set_client(ClientInfo(ip=ip, user_agent=request.headers.get("User-Agent")))
        started = time.perf_counter()
        response = await call_next(request)
        response.headers["X-Request-ID"] = rid
        response.headers["X-Response-Time-ms"] = f"{(time.perf_counter() - started) * 1000:.1f}"
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Referrer-Policy"] = "no-referrer"
        if not s.is_dev:
            response.headers["Strict-Transport-Security"] = "max-age=63072000; includeSubDomains"
        return response

    register_exception_handlers(app)

    api = APIRouter(prefix=s.api_prefix)
    for r in (
        auth_router,
        users_router,
        companies_router,
        admin_users_router,
        calc_router,
        contracts_router,
        rules_router,
        templates_router,
        moderation_router,
        scan_router,
        obligations_router,
        cases_router,
        notifications_router,
        files_router,
        audit_router,
        anchoring_router,
        assistant_router,
    ):
        api.include_router(r)
    app.include_router(api)

    @app.get(f"{s.api_prefix}/meta", tags=["health"], summary="Frontend uchun platforma sozlamalari")
    async def meta() -> dict[str, object]:
        return {
            "app": s.app_name,
            "environment": s.environment.value,
            # Dev only: the fixed OTP so testers aren't blocked by the console SMS gateway.
            "dev_otp_code": s.otp_dev_fixed_code if s.is_dev else None,
            "features": {
                "eimzo": bool(s.eimzo_server_url),
                "anchoring": s.anchor_backend.value != "disabled",
                "pdf": bool(s.soffice_path or shutil.which("soffice")),
                "ai": s.llm_provider.value != "none",
            },
            "ai": {
                "enabled": s.llm_provider.value != "none",
                "model": s.llm_model if s.llm_provider.value != "none" else None,
                "local": s.llm_is_local,
            },
        }

    @app.get("/health/live", tags=["health"])
    async def live() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/health/ready", tags=["health"])
    async def ready() -> dict[str, str]:
        async with get_engine().connect() as conn:
            await conn.execute(text("SELECT 1"))
        return {"status": "ready"}

    # Web SDK (packages/web-sdk): the JS client the web app loads from /sdk/lexlab-api.js,
    # versioned together with the API it talks to.
    sdk = Path(__file__).resolve().parents[3] / "packages" / "web-sdk"
    if sdk.is_dir():
        app.mount("/sdk", StaticFiles(directory=sdk), name="sdk")

    if s.frontend_dir:
        web = Path(s.frontend_dir).expanduser().resolve()
        if (web / "index.html").is_file():
            # Mounted last: /api/*, /docs and /health keep priority; everything else is the web app.
            app.mount("/", StaticFiles(directory=web, html=True), name="web")
        else:
            logging.getLogger(__name__).warning("FRONTEND_DIR has no index.html: %s", web)

    return app


app = create_app()
