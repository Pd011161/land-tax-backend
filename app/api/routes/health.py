"""
────────────────────────
GET /api/v1/health

ตรวจสอบสถานะ services ทั้งหมด:
  - vertex_ai_vision : ทดสอบโหลด credentials จริง (ไม่ call Vertex API)
  - google_maps      : ตรวจสอบ API key config
  - tax_engine       : smoke test ด้วย calculation เล็ก ๆ
"""
from __future__ import annotations

import time
from typing import Literal

from fastapi import APIRouter, Request
from loguru import logger
from pydantic import BaseModel

router = APIRouter()


# ── Response schema ────────────────────────────────────────────

class ServiceStatus(BaseModel):
    status:     Literal["ok", "degraded", "error"]
    detail:     str | None = None
    latency_ms: float | None = None


class HealthDetail(BaseModel):
    status:   Literal["ok", "degraded", "error"]
    version:  str
    services: dict[str, ServiceStatus]


@router.get(
    "/health",
    response_model=HealthDetail,
    summary="Health check",
    description=(
        "ตรวจสอบสถานะ config + services\n\n"
        "- **ok** — พร้อมใช้งาน\n"
        "- **degraded** — ทำงานได้บางส่วน (เช่น ไม่มี Google Maps key)\n"
        "- **error** — มีปัญหา ต้องแก้ไขก่อนใช้งาน"
    ),
)
async def health(request: Request) -> HealthDetail:
    app      = request.app
    settings = app.settings
    services: dict[str, ServiceStatus] = {}

    # ── 1. Vertex AI Vision ───────────────────────────────────
    # โหลด credentials จริง — parse ไฟล์ / JSON string
    # ไม่ call Vertex API แต่ตรวจสอบว่า credentials load ได้
    t0 = time.perf_counter()
    try:
        from app.services.vision_service import _load_credentials
        vertex_cfg = settings.vertex_ai
        creds = _load_credentials(vertex_cfg)
        elapsed_ms = round((time.perf_counter() - t0) * 1000, 1)

        if creds is not None:
            email = getattr(creds, "service_account_email", "loaded")
            detail = (
                f"service_account: {email} | "
                f"model: {vertex_cfg.model} | "
                f"project: {vertex_cfg.project or '(from creds)'} | "
                f"location: {vertex_cfg.location}"
            )
        else:
            detail = (
                f"Application Default Credentials (ADC) | "
                f"model: {vertex_cfg.model} | "
                f"project: {vertex_cfg.project or 'from ADC'} | "
                f"location: {vertex_cfg.location}"
            )

        services["vertex_ai_vision"] = ServiceStatus(
            status="ok",
            detail=detail,
            latency_ms=elapsed_ms,
        )

    except FileNotFoundError as exc:
        logger.warning("Health check — Vertex credentials file not found: {}", exc)
        services["vertex_ai_vision"] = ServiceStatus(
            status="error",
            detail=f"credentials file not found: {exc}",
        )
    except Exception as exc:
        logger.warning("Health check — Vertex credentials error: {}", exc)
        services["vertex_ai_vision"] = ServiceStatus(
            status="error",
            detail=f"{type(exc).__name__}: {exc}",
        )

    # ── 2. Google Maps ────────────────────────────────────────
    gmap_key = settings.google_maps.api_key
    if gmap_key:
        # แสดงแค่ prefix + suffix ของ key ไม่ expose ทั้งหมด
        masked = f"{gmap_key[:6]}...{gmap_key[-4:]}" if len(gmap_key) > 10 else "***"
        services["google_maps"] = ServiceStatus(
            status="ok",
            detail=f"key configured ({masked})",
        )
    else:
        services["google_maps"] = ServiceStatus(
            status="degraded",
            detail="GOOGLE_MAPS_KEY not set — Lat/Lon satellite mode unavailable",
        )

    # ── 3. Tax engine smoke test ──────────────────────────────
    # รัน calculation เล็ก ๆ จริง เพื่อยืนยันว่า TaxService init ถูกต้อง
    t0 = time.perf_counter()
    try:
        from app.api.types.schemas import LandUsePercents
        result = app.tax_service.calculate(
            total_area_sqwah=1,
            land_use_percents=LandUsePercents(commercial=100),
        )
        assert result.total_tax_per_year >= 0, "tax must be non-negative"
        elapsed_ms = round((time.perf_counter() - t0) * 1000, 2)

        services["tax_engine"] = ServiceStatus(
            status="ok",
            detail=(
                f"calculation OK | "
                f"default_price={settings.tax.default_land_price_per_sqwah:,.0f} บ./ตร.ว. | "
                f"vacant_max_rate={settings.tax.vacant_land_max_rate * 100:.0f}%"
            ),
            latency_ms=elapsed_ms,
        )
    except Exception as exc:
        logger.error("Health check — tax engine smoke test failed: {}", exc)
        services["tax_engine"] = ServiceStatus(
            status="error",
            detail=f"{type(exc).__name__}: {exc}",
        )

    # ── Overall status ────────────────────────────────────────
    statuses = [s.status for s in services.values()]
    if any(s == "error" for s in statuses):
        overall: Literal["ok", "degraded", "error"] = "error"
    elif any(s == "degraded" for s in statuses):
        overall = "degraded"
    else:
        overall = "ok"

    return HealthDetail(
        status=overall,
        version=settings.app.version,
        services=services,
    )


@router.get("/config", summary="Frontend config (public API keys)", include_in_schema=False)
async def frontend_config(request: Request):
    """ส่ง non-secret config ให้ frontend (Maps key เป็น public key ใช้ restrict domain ในการป้องกัน)"""
    return {
        "google_maps_key": request.app.settings.google_maps.api_key,
    }