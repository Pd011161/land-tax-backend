"""
──────────────────────────
POST /api/v1/parcels          — บันทึกแปลงที่ดิน (พร้อมผลภาษี)
GET  /api/v1/parcels          — ดึงทุกแปลง (สำหรับแสดงบน map)
GET  /api/v1/parcels/{id}     — ดึงแปลงเดียว
PATCH /api/v1/parcels/{id}    — อัปเดต
DELETE /api/v1/parcels/{id}   — ลบ
"""
from __future__ import annotations

import json
import random

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_session
from app.services.parcel_service import ParcelService

router = APIRouter()


# ── Land price logic ──────────────────────────────────────────

def resolve_land_price(province: str | None, district: str | None, given: float | None) -> float:
    """
    ถ้า land_price_per_sqwah ถูกส่งมาแล้ว → ใช้ค่านั้น
    ถ้าไม่มี → คำนวณจาก province/district:

    BKK + เมือง     → 15,000
    BKK + ไม่เมือง  → random [7000, 8000, 9000]
    ไม่ BKK + เมือง → 10,000
    ไม่ BKK + ไม่เมือง → random [5000, 6000, 7000, 8000]
    """
    if given and given > 0:
        return given

    prov = (province or "").lower()
    dist = (district or "").lower()

    is_bkk   = "กรุงเทพ" in prov or "bangkok" in prov
    is_muang = "เมือง" in dist or "mueang" in dist

    if is_bkk and is_muang:
        return 15_000.0
    elif is_bkk and not is_muang:
        return float(random.choice([7000, 8000, 9000]))
    elif not is_bkk and is_muang:
        return 10_000.0
    else:
        return float(random.choice([5000, 6000, 7000, 8000]))


# ── Request/Response schemas ──────────────────────────────────

class PolygonPoint(BaseModel):
    lat: float
    lng: float


class SaveParcelRequest(BaseModel):
    # Location
    lat:     float
    lng:     float
    polygon: list[PolygonPoint]
    zoom:    int = 18

    # Address (from Geocoding API — frontend fills these)
    province:     str | None = None
    district:     str | None = None
    subdistrict:  str | None = None
    postal_code:  str | None = None
    full_address: str | None = None

    # Land data
    total_area_sqwah:     float | None = None
    land_price_per_sqwah: float | None = None   # optional — fallback ใช้ resolve_land_price()
    owner_type:           str = "individual"
    residence_status:     str = "na"
    building_value:       float | None = None
    years_unused:         int = 0

    # Analysis results
    land_use_percents:  dict | None = None
    ai_source:          str | None = None
    tax_result:         dict | None = None
    total_tax_per_year: float | None = None

    note: str | None = None


# ── Endpoints ─────────────────────────────────────────────────

@router.post("", status_code=201, summary="บันทึกแปลงที่ดิน")
async def save_parcel(
    body: SaveParcelRequest,
    session: AsyncSession = Depends(get_session),
):
    # Resolve land_price_per_sqwah จาก province/district ถ้าไม่ได้กรอกมา
    resolved_price = resolve_land_price(
        body.province,
        body.district,
        body.land_price_per_sqwah,
    )

    parcel_data: dict = {
        "lat":                  body.lat,
        "lng":                  body.lng,
        "polygon_json":         json.dumps([p.model_dump() for p in body.polygon]),
        "zoom":                 body.zoom,
        "province":             body.province,
        "district":             body.district,
        "subdistrict":          body.subdistrict,
        "postal_code":          body.postal_code,
        "full_address":         body.full_address,
        "total_area_sqwah":     body.total_area_sqwah,
        "land_price_per_sqwah": resolved_price,
        "owner_type":           body.owner_type,
        "residence_status":     body.residence_status,
        "building_value":       body.building_value,
        "years_unused":         body.years_unused,
        "ai_source":            body.ai_source,
        "tax_result_json":      json.dumps(body.tax_result) if body.tax_result else None,
        "total_tax_per_year":   body.total_tax_per_year,
        "note":                 body.note,
    }
    if body.land_use_percents:
        parcel_data["land_use_percents_json"] = json.dumps(body.land_use_percents)

    parcel = await ParcelService.create(session, parcel_data)
    return parcel.to_dict()


@router.get("", summary="ดึงทุกแปลง (สำหรับแสดงบน map)")
async def list_parcels(session: AsyncSession = Depends(get_session)):
    parcels = await ParcelService.get_all(session)
    return [p.to_dict() for p in parcels]


@router.get("/{parcel_id}", summary="ดึงแปลงเดียว")
async def get_parcel(parcel_id: int, session: AsyncSession = Depends(get_session)):
    parcel = await ParcelService.get_by_id(session, parcel_id)
    if not parcel:
        raise HTTPException(404, "ไม่พบแปลงที่ดิน")
    return parcel.to_dict()


@router.patch("/{parcel_id}", summary="อัปเดตข้อมูลแปลง")
async def update_parcel(
    parcel_id: int,
    body: dict,
    session: AsyncSession = Depends(get_session),
):
    parcel = await ParcelService.update(session, parcel_id, body)
    if not parcel:
        raise HTTPException(404, "ไม่พบแปลงที่ดิน")
    return parcel.to_dict()


@router.delete("/{parcel_id}", status_code=204, summary="ลบแปลง")
async def delete_parcel(parcel_id: int, session: AsyncSession = Depends(get_session)):
    ok = await ParcelService.delete(session, parcel_id)
    if not ok:
        raise HTTPException(404, "ไม่พบแปลงที่ดิน")