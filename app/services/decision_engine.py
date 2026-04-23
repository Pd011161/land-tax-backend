"""
────────────────────────────────
Decision Engine — orchestrates the full assessment flow:

    Input
      │
      ├── land_use_percents ครบ?
      │       YES → TaxService โดยตรง (skip AI)
      │       NO  → VisionService → normalize → TaxService
      │
      └── TaxSummary + LandUseAnalysisResult

ไม่มี state ใน Engine — แต่ละ request เป็น pure function call.
"""
from __future__ import annotations

from loguru import logger

from app.api.types.schemas import (
    AssessRequest,
    AssessResponse,
    LandUseAnalysisResult,
    LandUsePercents,
)
from app.services.tax_service import TaxService
from app.services.vision_service import VisionService


class DecisionEngine:
    def __init__(
        self,
        vision_service: VisionService,
        tax_service:    TaxService,
    ) -> None:
        self._vision = vision_service
        self._tax    = tax_service

    async def assess(self, req: AssessRequest) -> AssessResponse:
        """
        Full pipeline: input → land use analysis → tax calculation → response

        Decision path:
        - land_use_percents provided → Manual mode (skip AI)
        - image_base64 provided      → AI Vision mode
        """
        # ── Step 1: Resolve land use percentages ──────────────
        if req.land_use_percents is not None:
            logger.info("Decision: manual mode — percents provided, skipping AI")
            land_use = LandUseAnalysisResult(
                percents=req.land_use_percents,
                source="manual",
                ai_note=None,
            )
        else:
            logger.info("Decision: AI mode — sending image to Vision service")
            land_use = await self._vision.analyze_land_use(
                image_base64=req.image_base64,
                image_mime=req.image_mime,
                context=req.image_context,
                has_drawn_boundary=True,    # frontend always merges drawing layer
            )

        # ── Step 2: Convert % → area → value → tax ────────────
        logger.info(
            "Running tax engine | area={} ตร.ว. | percents={}",
            req.total_area_sqwah,
            land_use.percents.to_dict(),
        )

        # Resolve building value: กรอกเอง > คำนวณจาก area > 0
        resolved_building_value = req.resolve_building_value(land_use.percents)

        tax_summary = self._tax.calculate(
            total_area_sqwah=     req.total_area_sqwah,
            land_use_percents=    land_use.percents,
            owner_type=           req.owner_type,
            residence_status=     req.residence_status,
            land_price_per_sqwah= req.land_price_per_sqwah,
            building_value_total= resolved_building_value,
            years_unused=         req.years_unused,
        )

        logger.info(
            "Building value resolved | explicit={} resolved={:,.0f} (auto={})",
            req.building_value,
            resolved_building_value,
            req.building_value is None,
        )

        logger.info(
            "Assessment complete | total_tax={:,.0f} บาท/ปี | source={}",
            tax_summary.total_tax_per_year,
            land_use.source,
        )

        return AssessResponse(
            land_use=land_use,
            tax=tax_summary,
            input_summary={
                "total_area_sqwah":          req.total_area_sqwah,
                "land_price_per_sqwah":      req.land_price_per_sqwah,
                "building_value_explicit":   req.building_value,
                "building_value_resolved":   resolved_building_value,
                "owner_type":                req.owner_type,
                "residence_status":          req.residence_status,
                "mode":                      land_use.source,
            },
        )