"""FastAPI uygulama giris noktasi."""

from __future__ import annotations

import logging
import time
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware

from app.api.errors import register_exception_handlers
from app.api.v1.routers import analysis, datasets, meta, reports
from app.core.config import get_settings
from app.core.logging import (
    configure_logging,
    get_request_id,
    new_request_id,
    set_request_id,
)
from app.storage.db import create_all, dispose_engine, init_engine

_log = logging.getLogger(__name__)

DESCRIPTION = """
ERP ve reklam raporlarini yonetim dashboard'una ceviren analiz servisi.

**Mimarinin iki tasiyici fikri:**

1. **Dataset Pack** — boru hattinin tamami (okuma, kodlama onarimi, veri
   kalitesi, zaman serisi, risk tespiti, AI) rapor tipinden bagimsizdir. Bir
   rapora ozgu her sey tek bir yapilandirma nesnesinde toplanir. Yeni rapor
   eklemek = yeni pack yazmak.

2. **Sayiyi Polars hesaplar, AI yorumlar.** Modele ham veri hic verilmez;
   yalnizca hesaplanmis tablolar gider. Uretilen her aksiyon sema geregi kanit
   tasimak zorundadir ve her kanit hesaplanmis degerle karsilastirilarak
   dogrulanir (`grounding_ratio`).
"""


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    settings = get_settings()
    configure_logging(settings.log_level)
    init_engine(settings.database_url)
    await create_all()
    _log.info(
        "startup",
        extra={
            "env": settings.app_env,
            "ai_configured": settings.ai_configured,
            "ai_model": settings.ai_model,
        },
    )
    yield
    await dispose_engine()


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(
        title="Sonart Insight API",
        description=DESCRIPTION,
        version="0.1.0",
        lifespan=lifespan,
        openapi_url=f"{settings.api_prefix}/openapi.json",
        docs_url="/docs",
        redoc_url="/redoc",
    )

    # Next.js gelistirme sunucusu ayri portta calisiyor.
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["http://localhost:3000", "http://127.0.0.1:3000"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
        # Tarayici, CORS altinda yalnizca acikca acilan yanit basliklarini
        # okuyabilir. Bunlar olmadan frontend ne hata bildiriminde istek
        # kimligini gosterebilir ne de PDF'i dogru dosya adiyla indirebilir.
        expose_headers=["x-request-id", "x-response-time-ms", "content-disposition"],
    )

    @app.middleware("http")
    async def request_context(request: Request, call_next):
        """Her istege korelasyon kimligi ve sure olcumu ekler."""
        set_request_id(request.headers.get("x-request-id") or new_request_id())
        started = time.perf_counter()
        response = await call_next(request)
        duration_ms = int((time.perf_counter() - started) * 1000)
        response.headers["x-request-id"] = get_request_id()
        response.headers["x-response-time-ms"] = str(duration_ms)
        _log.info(
            "http_request",
            extra={
                "method": request.method,
                "path": request.url.path,
                "status": response.status_code,
                "duration_ms": duration_ms,
            },
        )
        return response

    register_exception_handlers(app)

    app.include_router(meta.router, prefix=settings.api_prefix)
    app.include_router(datasets.router, prefix=settings.api_prefix)
    app.include_router(analysis.router, prefix=settings.api_prefix)
    app.include_router(reports.router, prefix=settings.api_prefix)

    return app


app = create_app()
