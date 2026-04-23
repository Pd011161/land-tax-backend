"""
─────────────────────
AppState extends FastAPI — single dependency container, no globals.

ใช้ lifespan context manager (FastAPI ≥ 0.93) แทน on_event deprecated API

CORS note:
  dev  → เพิ่ม origins ใน config.yaml หรือ set CORS_ALLOW_ALL=true
  prod → ระบุ origins ที่แน่นอนใน config.yaml เท่านั้น
"""
from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from loguru import logger

from app.core.config import Settings, get_settings
from app.core.database import close_db, create_tables, init_db, get_session
from app.services.decision_engine import DecisionEngine
from app.services.map_service import MapService
from app.services.tax_service import TaxService
from app.services.vision_service import VisionService


class AppState(FastAPI):
    settings:       Settings
    vision_service: VisionService
    map_service:    MapService
    tax_service:    TaxService
    decision_engine: DecisionEngine


def create_app() -> AppState:
    settings = get_settings()

    @asynccontextmanager
    async def lifespan(application: AppState):
        # ── Startup ───────────────────────────────────────────
        logger.info("Starting up Land Tax API...")

        # Init database (optional — graceful degradation if DB unavailable)
        try:
            init_db(settings.database_url)
            await create_tables()
            logger.info("Database initialized ✓")
        except Exception as exc:
            logger.warning("Database unavailable — parcel endpoints disabled: {}", exc)

        application.settings        = settings
        application.vision_service  = VisionService(settings.vertex_ai)
        application.map_service     = MapService(settings.google_maps)
        application.tax_service     = TaxService(settings.tax)
        application.decision_engine = DecisionEngine(
            vision_service=application.vision_service,
            tax_service=application.tax_service,
        )

        cors = settings.app.cors_origins
        if cors == ["*"]:
            logger.warning("CORS: allowing ALL origins — dev mode only")
        else:
            logger.info("CORS: allowed origins = {}", cors)

        logger.info("Land Tax API ready ✓")
        yield
        # ── Shutdown ──────────────────────────────────────────
        await application.map_service.close()
        try:
            await close_db()
        except Exception:
            pass
        logger.info("Land Tax API shutdown complete")

    # Register routes BEFORE startup (correct FastAPI pattern)
    from app.api.routes import health, maps, tax, parcels

    app = AppState(
        title=settings.app.name,
        version=settings.app.version,
        docs_url="/docs",
        redoc_url=None,
        lifespan=lifespan,
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.app.cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    app.include_router(health.router,    prefix="/api/v1",          tags=["health"])
    app.include_router(tax.router,       prefix="/api/v1/tax",      tags=["tax"])
    app.include_router(maps.router,      prefix="/api/v1/maps",     tags=["maps"])
    app.include_router(parcels.router,   prefix="/api/v1/parcels",  tags=["parcels"])

    return app


app = create_app()