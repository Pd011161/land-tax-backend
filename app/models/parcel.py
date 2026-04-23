"""
SQLAlchemy ORM model สำหรับ land parcel ที่บันทึกแต่ละแปลง
"""
from __future__ import annotations

import json
from datetime import datetime
from typing import Any

from sqlalchemy import (
    BigInteger, Column, DateTime, Float, Integer,
    String, Text, func,
)
from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    pass


class LandParcel(Base):
    """
    เก็บข้อมูลแปลงที่ดินแต่ละแปลงที่ user ตีกรอบและบันทึก

    polygon  : GeoJSON-style list of {lat, lng} points
    tax_data : ผลคำนวณภาษีทั้งหมด (JSON)
    """
    __tablename__ = "land_parcels"

    id              = Column(BigInteger, primary_key=True, autoincrement=True)
    created_at      = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at      = Column(DateTime(timezone=True), server_default=func.now(),
                             onupdate=func.now(), nullable=False)

    # Location
    lat             = Column(Float,   nullable=False)
    lng             = Column(Float,   nullable=False)
    polygon_json    = Column(Text,    nullable=False)   # JSON [{lat,lng},...]
    zoom            = Column(Integer, default=18)

    # Address (from Geocoding API)
    province        = Column(String(100), nullable=True)
    district        = Column(String(100), nullable=True)
    subdistrict     = Column(String(100), nullable=True)
    postal_code     = Column(String(20),  nullable=True)
    full_address    = Column(Text,        nullable=True)

    # Land data
    total_area_sqwah    = Column(Float,   nullable=True)
    land_price_per_sqwah = Column(Float,  nullable=True)
    owner_type          = Column(String(20),  default="individual")
    residence_status    = Column(String(10),  default="na")
    building_value      = Column(Float,   nullable=True)
    years_unused        = Column(Integer, default=0)

    # AI analysis
    land_use_percents_json = Column(Text, nullable=True)   # JSON
    ai_source              = Column(String(20), nullable=True)  # manual/ai/ai_fallback

    # Tax result
    tax_result_json = Column(Text, nullable=True)   # full TaxSummary JSON
    total_tax_per_year = Column(Float, nullable=True)

    # Note
    note = Column(Text, nullable=True)

    # ── Helpers ──────────────────────────────────────────────

    @property
    def polygon(self) -> list[dict]:
        return json.loads(self.polygon_json) if self.polygon_json else []

    @polygon.setter
    def polygon(self, value: list[dict]) -> None:
        self.polygon_json = json.dumps(value, ensure_ascii=False)

    @property
    def land_use_percents(self) -> dict | None:
        return json.loads(self.land_use_percents_json) if self.land_use_percents_json else None

    @land_use_percents.setter
    def land_use_percents(self, value: dict) -> None:
        self.land_use_percents_json = json.dumps(value, ensure_ascii=False)

    @property
    def tax_result(self) -> dict | None:
        return json.loads(self.tax_result_json) if self.tax_result_json else None

    @tax_result.setter
    def tax_result(self, value: dict) -> None:
        self.tax_result_json = json.dumps(value, ensure_ascii=False)

    def to_dict(self) -> dict:
        return {
            "id":                   self.id,
            "created_at":           self.created_at.isoformat() if self.created_at else None,
            "lat":                  self.lat,
            "lng":                  self.lng,
            "polygon":              self.polygon,
            "zoom":                 self.zoom,
            "province":             self.province,
            "district":             self.district,
            "subdistrict":          self.subdistrict,
            "postal_code":          self.postal_code,
            "full_address":         self.full_address,
            "total_area_sqwah":     self.total_area_sqwah,
            "land_price_per_sqwah": self.land_price_per_sqwah,
            "owner_type":           self.owner_type,
            "residence_status":     self.residence_status,
            "building_value":       self.building_value,
            "years_unused":         self.years_unused,
            "land_use_percents":    self.land_use_percents,
            "ai_source":            self.ai_source,
            "tax_result":           self.tax_result,
            "total_tax_per_year":   self.total_tax_per_year,
            "note":                 self.note,
        }