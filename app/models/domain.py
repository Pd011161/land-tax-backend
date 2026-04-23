"""
────────────────────
Internal domain dataclasses — ใช้ภายใน services เท่านั้น

อัตราภาษีที่ดินและสิ่งปลูกสร้าง ปี 2569
อ้างอิง: พ.ร.บ. ภาษีที่ดินและสิ่งปลูกสร้าง พ.ศ. 2562 + กฎกระทรวงล่าสุด
"""
from __future__ import annotations

from dataclasses import dataclass


# ── Tax bracket definition ────────────────────────────────────

@dataclass(frozen=True)
class TaxBracket:
    """
    Immutable tax bracket สำหรับคำนวณ progressive tax.

    threshold : มูลค่าสูงสุดของ bracket นี้ (บาท)
                ใช้ float('inf') สำหรับ bracket สุดท้าย
    rate      : อัตราภาษี เช่น 0.003 = 0.3%
    label     : label แสดงใน response
    """
    threshold: float
    rate: float
    label: str

    def tax_in_bracket(self, value_above_prev: float) -> float:
        return value_above_prev * self.rate


# ── Bracket tables — อัตราภาษีปี 2569 ───────────────────────

# ที่อยู่อาศัย หลังที่ 2 ขึ้นไป / ให้เช่า (บุคคลธรรมดาและนิติบุคคล)
# 0–50 ล. → 0.02%, 50–75 ล. → 0.03%, 75–100 ล. → 0.05%, 100 ล.+ → 0.10%
RESIDENTIAL_OTHER_BRACKETS: tuple[TaxBracket, ...] = (
    TaxBracket(threshold=50_000_000,    rate=0.0002, label="0.02%"),
    TaxBracket(threshold=75_000_000,    rate=0.0003, label="0.03%"),
    TaxBracket(threshold=100_000_000,   rate=0.0005, label="0.05%"),
    TaxBracket(threshold=float("inf"),  rate=0.001,  label="0.10%"),
)

# ที่อยู่อาศัย หลักหลัก ส่วนที่เกิน 50 ล้านบาท
# 50–75 ล. → 0.03%, 75–100 ล. → 0.05%, 100 ล.+ → 0.10%
RESIDENTIAL_PRIMARY_OVER_50M_BRACKETS: tuple[TaxBracket, ...] = (
    TaxBracket(threshold=75_000_000,    rate=0.0003, label="0.03%"),
    TaxBracket(threshold=100_000_000,   rate=0.0005, label="0.05%"),
    TaxBracket(threshold=float("inf"),  rate=0.001,  label="0.10%"),
)

# เกษตรกรรม — บุคคลธรรมดา (ส่วนที่เกิน 50 ล้านบาท)
# 50–125 ล. → 0.01%, 125–150 ล. → 0.03%, 150–550 ล. → 0.05%
# 550–1,050 ล. → 0.07%, 1,050 ล.+ → 0.10%
AGRICULTURE_INDIVIDUAL_OVER_50M_BRACKETS: tuple[TaxBracket, ...] = (
    TaxBracket(threshold=125_000_000,   rate=0.0001, label="0.01%"),
    TaxBracket(threshold=150_000_000,   rate=0.0003, label="0.03%"),
    TaxBracket(threshold=550_000_000,   rate=0.0005, label="0.05%"),
    TaxBracket(threshold=1_050_000_000, rate=0.0007, label="0.07%"),
    TaxBracket(threshold=float("inf"),  rate=0.001,  label="0.10%"),
)

# เกษตรกรรม — นิติบุคคล (ทุกมูลค่า)
# 0–75 ล. → 0.01%, 75–100 ล. → 0.03%, 100–500 ล. → 0.05%
# 500–1,000 ล. → 0.07%, 1,000 ล.+ → 0.10%
AGRICULTURE_JURISTIC_BRACKETS: tuple[TaxBracket, ...] = (
    TaxBracket(threshold=75_000_000,    rate=0.0001, label="0.01%"),
    TaxBracket(threshold=100_000_000,   rate=0.0003, label="0.03%"),
    TaxBracket(threshold=500_000_000,   rate=0.0005, label="0.05%"),
    TaxBracket(threshold=1_000_000_000, rate=0.0007, label="0.07%"),
    TaxBracket(threshold=float("inf"),  rate=0.001,  label="0.10%"),
)

# พาณิชยกรรม และ รกร้างว่างเปล่า (ใช้ bracket เดียวกัน)
# 0–50 ล. → 0.30%, 50–200 ล. → 0.40%, 200–1,000 ล. → 0.50%
# 1,000–5,000 ล. → 0.60%, 5,000 ล.+ → 0.70%
COMMERCIAL_BRACKETS: tuple[TaxBracket, ...] = (
    TaxBracket(threshold=50_000_000,      rate=0.003,  label="0.30%"),
    TaxBracket(threshold=200_000_000,     rate=0.004,  label="0.40%"),
    TaxBracket(threshold=1_000_000_000,   rate=0.005,  label="0.50%"),
    TaxBracket(threshold=5_000_000_000,   rate=0.006,  label="0.60%"),
    TaxBracket(threshold=float("inf"),    rate=0.007,  label="0.70%"),
)

# รกร้างว่างเปล่า — ใช้ bracket เดียวกับพาณิชย์
VACANT_BRACKETS: tuple[TaxBracket, ...] = COMMERCIAL_BRACKETS


# ── Progressive tax calculator ────────────────────────────────

def calc_progressive_tax(value: float, brackets: tuple[TaxBracket, ...]) -> float:
    """
    คำนวณภาษีแบบ progressive ข้ามหลาย brackets

    value    : มูลค่าทรัพย์สิน (บาท) — เริ่มจาก 0 เสมอ
    brackets : ตาราง TaxBracket เรียงจาก threshold น้อย → มาก
    """
    tax = 0.0
    prev = 0.0
    for b in brackets:
        if value <= prev:
            break
        taxable = min(value, b.threshold) - prev
        tax += taxable * b.rate
        prev = b.threshold
    return tax


def calc_progressive_tax_from(
    value: float,
    brackets: tuple[TaxBracket, ...],
    start_from: float,
) -> float:
    """
    คำนวณภาษีแบบ progressive เริ่มจาก start_from (floor)
    ใช้สำหรับ หลักหลัก และ เกษตร บุคคลธรรมดา ที่มี exempt threshold

    value      : มูลค่าทรัพย์สินทั้งหมด (absolute)
    brackets   : ตาราง TaxBracket ที่มี threshold เป็น absolute value
    start_from : มูลค่า exempt floor (บาท) เช่น 50_000_000

    สำคัญ: iterate ด้วย absolute value ทั้งหมด
    เช่น หลักหลัก 120 ล้าน, floor=50 ล.:
      bracket 50–75 ล. @ 0.03% → 25 ล. × 0.03% = 7,500
      bracket 75–100 ล. @ 0.05% → 25 ล. × 0.05% = 12,500
      bracket 100 ล.+ @ 0.10% → 20 ล. × 0.10% = 20,000
    """
    if value <= start_from:
        return 0.0
    tax = 0.0
    prev = start_from
    for b in brackets:
        if value <= prev:
            break
        taxable = min(value, b.threshold) - prev
        tax += taxable * b.rate
        prev = b.threshold
    return tax


def bracket_label_for(value: float, brackets: tuple[TaxBracket, ...]) -> str:
    """label ของ bracket ที่ value ตกอยู่ (แสดงเฉพาะ brackets ที่ถูกใช้)"""
    prev = 0.0
    labels = []
    for b in brackets:
        if value > prev:
            labels.append(b.label)
        prev = b.threshold
    return "–".join(dict.fromkeys(labels)) if labels else brackets[0].label


# ── Assessment context ────────────────────────────────────────

@dataclass
class AssessmentContext:
    """Intermediate state ระหว่าง DecisionEngine steps"""
    total_area_sqwah:     float
    land_price_per_sqwah: float
    building_value_total: float
    is_primary_residence: bool
    is_individual:        bool
    years_unused:         int = 0   # จำนวนปีที่ดินรกร้างต่อเนื่อง

    @property
    def total_land_value(self) -> float:
        return self.total_area_sqwah * self.land_price_per_sqwah

    @property
    def total_property_value(self) -> float:
        return self.total_land_value + self.building_value_total

    def land_value_for_pct(self, pct: float) -> float:
        return (pct / 100) * self.total_area_sqwah * self.land_price_per_sqwah

    def building_value_for_pct(self, pct: float) -> float:
        return (pct / 100) * self.building_value_total

    def total_value_for_pct(self, pct: float) -> float:
        return self.land_value_for_pct(pct) + self.building_value_for_pct(pct)