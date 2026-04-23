"""
────────────────────────
All request/response Pydantic models for the Tax API.
"""
from __future__ import annotations

from enum import Enum
from typing import Annotated

from pydantic import BaseModel, Field, model_validator


# ── Enums ─────────────────────────────────────────────────────

class OwnerType(str, Enum):
    individual = "individual"   # บุคคลธรรมดา
    juristic   = "juristic"     # นิติบุคคล


class ResidenceStatus(str, Enum):
    primary = "yes"   # หลักหลัก — มีชื่อในโฉนด + ทะเบียนบ้าน
    other   = "no"    # บ้านหลังที่ 2 / ให้เช่า
    na      = "na"    # ไม่ใช่ที่อยู่อาศัย


class LandUseCategory(str, Enum):
    residential = "residential"
    agriculture  = "agriculture"
    commercial   = "commercial"
    vacant       = "vacant"


# ── Land Use Percentages ───────────────────────────────────────

class LandUsePercents(BaseModel):
    """สัดส่วนการใช้ที่ดิน — รวมต้องได้ 100"""
    residential: Annotated[float, Field(ge=0, le=100)] = 0
    agriculture:  Annotated[float, Field(ge=0, le=100)] = 0
    commercial:   Annotated[float, Field(ge=0, le=100)] = 0
    vacant:       Annotated[float, Field(ge=0, le=100)] = 0

    @model_validator(mode="after")
    def total_must_be_100(self) -> "LandUsePercents":
        total = self.residential + self.agriculture + self.commercial + self.vacant
        if abs(total - 100) > 0.5:
            raise ValueError(f"สัดส่วนรวมต้องเท่ากับ 100 (ได้ {total:.1f})")
        return self

    def normalize(self) -> "LandUsePercents":
        """ปรับให้รวม = 100 พอดี กรณี AI ส่งมาไม่ครบ"""
        total = self.residential + self.agriculture + self.commercial + self.vacant
        if total == 0:
            return self
        scale = 100 / total
        return LandUsePercents(
            residential=round(self.residential * scale, 2),
            agriculture= round(self.agriculture  * scale, 2),
            commercial=  round(self.commercial   * scale, 2),
            vacant=      round(self.vacant       * scale, 2),
        )

    def to_dict(self) -> dict[str, float]:
        return {
            "residential": self.residential,
            "agriculture":  self.agriculture,
            "commercial":   self.commercial,
            "vacant":       self.vacant,
        }


# ── Requests ──────────────────────────────────────────────────

class AssessRequest(BaseModel):
    """
    Main assessment request.

    Decision Engine logic:
    - ถ้า land_use_percents ครบ → ข้าม AI → คำนวณ tax เลย
    - ถ้าไม่มี → ต้องมี image_base64 (จาก upload หรือ Google Maps)
    """
    # ── ข้อมูลที่ดิน (จำเป็น)
    total_area_sqwah: Annotated[float, Field(gt=0, description="พื้นที่ทั้งหมด หน่วยตารางวา")]
    owner_type:       OwnerType        = OwnerType.individual
    residence_status: ResidenceStatus  = ResidenceStatus.na

    # ── ราคาประเมิน (จำเป็น — ดูได้ที่ assessprice.treasury.go.th)
    land_price_per_sqwah: Annotated[float, Field(gt=0, description="ราคาประเมินทุนทรัพย์จากกรมธนารักษ์ บาท/ตร.ว.")]

    # ── สิ่งปลูกสร้าง (optional — กรอกเองหรือให้ระบบคำนวณอัตโนมัติ)
    building_value: Annotated[float | None, Field(ge=0, description="มูลค่าสิ่งปลูกสร้างรวม บาท · ถ้าไม่กรอก ระบบคำนวณจากพื้นที่ที่ดิน × สัดส่วน res+com × 4 ตร.ม./ตร.ว. × อัตรา")] = None

    # ── ที่ดินรกร้าง: จำนวนปีที่ปล่อยรกร้างต่อเนื่อง (ใช้คำนวณภาษีเพิ่ม)
    years_unused: Annotated[int, Field(ge=0, le=100, description="จำนวนปีที่ปล่อยรกร้างต่อเนื่อง (0 = ปีแรก)")] = 0

    # ── การใช้งานที่ดิน (กรอกเองหรือให้ AI วิเคราะห์)
    land_use_percents: LandUsePercents | None = None   # ถ้ามี → skip AI
    image_base64:      str | None = None               # ภาพสำหรับ AI วิเคราะห์
    image_mime:        str        = "image/jpeg"
    image_context:     str | None = None               # บริบทเพิ่มเติมให้ AI

    @model_validator(mode="after")
    def validate_inputs(self) -> "AssessRequest":
        if self.land_use_percents is None and self.image_base64 is None:
            raise ValueError(
                "ต้องระบุ land_use_percents (กรอกเอง) หรือ image_base64 (ให้ AI วิเคราะห์) อย่างใดอย่างหนึ่ง"
            )
        return self

    def resolve_building_value(self, percents: "LandUsePercents") -> float:
        """
        คำนวณมูลค่าสิ่งปลูกสร้าง:

        1. กรอก building_value เอง → ใช้ค่านั้น
        2. ไม่กรอก + มี res หรือ com → คำนวณอัตโนมัติ:
             พื้นที่อาคาร (ตร.ม.) = total_area_sqwah × (res% + com%) / 100 × 4
             (1 ตร.ว. = 4 ตร.ม.)
             อัตรา: residential = 15,000 บ./ตร.ม.
                    commercial  = 25,000 บ./ตร.ม.
             blended rate = weighted avg ตามสัดส่วน
        3. ไม่มี res/com เลย → 0
        """
        if self.building_value is not None:
            return self.building_value

        total_bldg_pct = percents.residential + percents.commercial
        if total_bldg_pct <= 0:
            return 0.0

        # พื้นที่อาคาร = พื้นที่ที่ดินส่วนที่มีอาคาร × 4 ตร.ม./ตร.ว.
        building_area_sqm = self.total_area_sqwah * (total_bldg_pct / 100) * 4

        res_w        = percents.residential / total_bldg_pct
        com_w        = percents.commercial  / total_bldg_pct
        blended_rate = res_w * 15_000.0 + com_w * 25_000.0

        return building_area_sqm * blended_rate


class MapImageRequest(BaseModel):
    """ดึงภาพดาวเทียมจาก Google Maps Static API"""
    latitude:  Annotated[float, Field(ge=-90,  le=90)]
    longitude: Annotated[float, Field(ge=-180, le=180)]
    zoom:      Annotated[int,   Field(ge=1,    le=21)]  = 18


class AnalyzeImageRequest(BaseModel):
    """วิเคราะห์ภาพ (standalone — สำหรับ debug)"""
    image_base64: str
    image_mime:   str   = "image/jpeg"
    context:      str | None = None


# ── Per-category tax result ────────────────────────────────────

class CategoryTaxResult(BaseModel):
    category:      LandUseCategory
    category_label: str
    percent:       float
    area_sqwah:    float
    land_value:    float
    building_value: float
    total_value:   float
    tax_amount:    float
    rate_label:    str


# ── Responses ─────────────────────────────────────────────────

class LandUseAnalysisResult(BaseModel):
    percents:     LandUsePercents
    source:       str                   # "manual" | "ai" | "ai_fallback"
    ai_note:      str | None = None
    model_used:   str | None = None


class TaxSummary(BaseModel):
    total_land_value:     float
    total_building_value: float
    total_property_value: float
    total_tax_per_year:   float
    breakdown:            list[CategoryTaxResult]
    notes:                list[str]


class AssessResponse(BaseModel):
    status:          str = "success"
    land_use:        LandUseAnalysisResult
    tax:             TaxSummary
    input_summary:   dict


class MapImageResponse(BaseModel):
    status:       str = "success"
    image_base64: str
    image_mime:   str
    lat:          float
    lon:          float
    zoom:         int


class HealthResponse(BaseModel):
    status:   str = "ok"
    version:  str
    services: dict[str, str]


class ErrorResponse(BaseModel):
    status:  str = "error"
    message: str
    detail:  str | None = None