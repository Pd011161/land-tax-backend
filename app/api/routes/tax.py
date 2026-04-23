"""
──────────────────────
POST /api/v1/tax/assess  — main assessment endpoint
"""
from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request
from loguru import logger

from app.api.types.schemas import (
    AnalyzeImageRequest,
    AssessRequest,
    AssessResponse,
    ErrorResponse,
    LandUseAnalysisResult,
)

router = APIRouter()


@router.post(
    "/assess",
    response_model=AssessResponse,
    responses={422: {"model": ErrorResponse}, 500: {"model": ErrorResponse}},
    summary="ประเมินภาษีที่ดินและสิ่งปลูกสร้าง",
    description="""
**Decision Engine flow:**

1. ถ้า `land_use_percents` ครบ → คำนวณ tax โดยตรง (skip AI)
2. ถ้าไม่มี → ส่ง `image_base64` ไปให้ AI Vision วิเคราะห์ % → คำนวณ tax
""",
)
async def assess(req: AssessRequest, request: Request) -> AssessResponse:
    app = request.app
    try:
        return await app.decision_engine.assess(req)
    except ValueError as exc:
        logger.warning("Validation error in assess: {}", exc)
        raise HTTPException(status_code=422, detail=str(exc))
    except Exception as exc:
        logger.error("Unexpected error in assess: {}", exc)
        raise HTTPException(status_code=500, detail=f"Internal error: {exc}")


@router.post(
    "/analyze-image",
    response_model=LandUseAnalysisResult,
    summary="วิเคราะห์ภาพอย่างเดียว (debug / preview)",
)
async def analyze_image(req: AnalyzeImageRequest, request: Request) -> LandUseAnalysisResult:
    """ส่งภาพไปวิเคราะห์ % การใช้ที่ดิน โดยไม่คำนวณภาษี"""
    app = request.app
    try:
        return await app.vision_service.analyze_land_use(
            image_base64=req.image_base64,
            image_mime=req.image_mime,
            context=req.context,
        )
    except Exception as exc:
        logger.error("analyze-image error: {}", exc)
        raise HTTPException(status_code=500, detail=str(exc))
