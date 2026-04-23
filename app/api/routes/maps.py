"""
───────────────────────
POST /api/v1/maps/satellite  — ดึงภาพดาวเทียมจาก Google Maps
"""
from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request
from loguru import logger

from app.api.types.schemas import MapImageRequest, MapImageResponse

router = APIRouter()


@router.post(
    "/satellite",
    response_model=MapImageResponse,
    summary="ดึงภาพดาวเทียม Google Maps",
    description="รับ lat/lon/zoom → คืน image_base64 พร้อมใช้ใน /tax/assess",
)
async def get_satellite_image(req: MapImageRequest, request: Request) -> MapImageResponse:
    app = request.app
    try:
        return await app.map_service.fetch_satellite_image(
            lat=req.latitude,
            lon=req.longitude,
            zoom=req.zoom,
        )
    except ValueError as exc:
        logger.warning("Map fetch error: {}", exc)
        raise HTTPException(status_code=400, detail=str(exc))
    except Exception as exc:
        logger.error("Unexpected map error: {}", exc)
        raise HTTPException(status_code=500, detail=str(exc))
