"""
────────────────────────────
Tax Engine — อัตราภาษีปี 2569

# ────────────────────────────
# Tax Engine — คำนวณภาษีที่ดินและสิ่งปลูกสร้าง
# ตาม พ.ร.บ. ภาษีที่ดินและสิ่งปลูกสร้าง พ.ศ. 2562 (อัตราปี 2567–2568)

# อัตราภาษีแยกตามประเภท:
# ┌──────────────────────────────┬─────────────────────┬──────────────────┐
# │ ประเภท                       │ มูลค่า (ล้านบาท)    │ อัตรา           │
# ├──────────────────────────────┼─────────────────────┼──────────────────┤
# │ เกษตร (บุคคลธรรมดา)         │ 0–50                │ ยกเว้น          │
# │                              │ >50                 │ 0.10%            │
# │ ที่อยู่อาศัย (หลักหลัก)     │ 0–50                │ ยกเว้น          │
# │                              │ >50                 │ 0.10%            │
# │ ที่อยู่อาศัย (หลังอื่น)     │ 0–50                │ 0.02%           │
# │                              │ >50–90              │ 0.03%           │
# │                              │ >90–100             │ 0.05%           │
# │                              │ >100                │ 0.10%           │
# │ พาณิชยกรรม                  │ 0–50                │ 0.30%           │
# │                              │ 50–200              │ 0.40%           │
# │                              │ >200                │ 0.50%           │
# │ รกร้างว่างเปล่า              │ เริ่มต้น            │ 0.30%           │
# │                              │ เพดานสูงสุด         │ 3.00%           │
# └──────────────────────────────┴─────────────────────┴──────────────────┘

ที่ดินรกร้างว่างเปล่า: เพิ่มอัตรา 0.3% ทุก 3 ปี สูงสุด 3%
  years_unused = 0–2  → 0.30%  (bracket base)
  years_unused = 3–5  → +0.30% = 0.60%
  years_unused = 6–8  → +0.60% = 0.90%
  ...
  years_unused ≥ 27   → สูงสุด 3.00%
"""
from __future__ import annotations

import math
from dataclasses import dataclass

from loguru import logger

from app.api.types.schemas import (
    CategoryTaxResult,
    LandUseCategory,
    LandUsePercents,
    OwnerType,
    ResidenceStatus,
    TaxSummary,
)
from app.core.config import TaxConfig
from app.models.domain import (
    AGRICULTURE_INDIVIDUAL_OVER_50M_BRACKETS,
    AGRICULTURE_JURISTIC_BRACKETS,
    COMMERCIAL_BRACKETS,
    RESIDENTIAL_OTHER_BRACKETS,
    RESIDENTIAL_PRIMARY_OVER_50M_BRACKETS,
    VACANT_BRACKETS,
    AssessmentContext,
    TaxBracket,
    bracket_label_for,
    calc_progressive_tax,
    calc_progressive_tax_from,
)

CATEGORY_LABELS: dict[LandUseCategory, str] = {
    LandUseCategory.residential: "ที่อยู่อาศัย",
    LandUseCategory.agriculture:  "เกษตรกรรม",
    LandUseCategory.commercial:   "พาณิชยกรรม",
    LandUseCategory.vacant:       "รกร้างว่างเปล่า",
}

EXEMPT_50M = 50_000_000


@dataclass
class _TaxCalcResult:
    tax_amount:      float
    rate_label:      str
    surcharge_note:  str | None = None   # note สำหรับที่ดินรกร้าง


class TaxService:
    def __init__(self, config: TaxConfig) -> None:
        self._cfg = config
        logger.info(
            "TaxService initialized | default_land_price={}/ตร.ว.",
            config.default_land_price_per_sqwah,
        )

    # ── Vacant surcharge calculator ───────────────────────────

    def calc_vacant_surcharge_rate(self, years_unused: int) -> float:
        """
        คำนวณอัตราภาษีเพิ่มสำหรับที่ดินรกร้าง

        กฎ: เพิ่ม 0.3% ทุก 3 ปีที่ปล่อยรกร้าง สูงสุด 3%
          years 0–2   → +0.0% (base rate เท่านั้น)
          years 3–5   → +0.3%
          years 6–8   → +0.6%
          ...
          years 27+   → +2.7% (รวม base 0.3% = 3.0% cap)

        Returns: surcharge rate (เช่น 0.003 = 0.3%)
        """
        if years_unused < self._cfg.vacant_land_increment_years:
            return 0.0
        increments = years_unused // self._cfg.vacant_land_increment_years
        surcharge  = increments * 0.003   # +0.3% per period
        max_surcharge = self._cfg.vacant_land_max_rate - 0.003  # cap total at 3%
        return min(surcharge, max_surcharge)

    def calc_effective_vacant_rate(self, base_rate: float, years_unused: int) -> float:
        """อัตราภาษีจริงหลังบวก surcharge (cap 3%)"""
        surcharge = self.calc_vacant_surcharge_rate(years_unused)
        return min(base_rate + surcharge, self._cfg.vacant_land_max_rate)

    # ── Main calculate ────────────────────────────────────────

    def calculate(
        self,
        total_area_sqwah:     float,
        land_use_percents:    LandUsePercents,
        owner_type:           OwnerType       = OwnerType.individual,
        residence_status:     ResidenceStatus = ResidenceStatus.na,
        land_price_per_sqwah: float           = 0.0,
        building_value_total: float | None    = None,
        years_unused:         int             = 0,
    ) -> TaxSummary:
        """
        Parameters
        ----------
        total_area_sqwah     : พื้นที่ทั้งหมด (ตร.ว.)
        land_use_percents    : สัดส่วนการใช้ที่ดิน (รวม 100%)
        owner_type           : บุคคลธรรมดา / นิติบุคคล
        residence_status     : สถานะที่อยู่อาศัย
        land_price_per_sqwah : ราคาประเมินทุนทรัพย์จากกรมธนารักษ์ บาท/ตร.ว.
        building_value_total : มูลค่าสิ่งปลูกสร้างรวม (บาท)
        years_unused         : จำนวนปีที่ปล่อยรกร้างต่อเนื่อง
        """
        ctx = AssessmentContext(
            total_area_sqwah=     total_area_sqwah,
            land_price_per_sqwah= land_price_per_sqwah or self._cfg.default_land_price_per_sqwah,
            building_value_total= building_value_total or 0.0,
            is_primary_residence= residence_status == ResidenceStatus.primary,
            is_individual=        owner_type == OwnerType.individual,
            years_unused=         years_unused,
        )

        pct_map: dict[LandUseCategory, float] = {
            LandUseCategory.residential: land_use_percents.residential,
            LandUseCategory.agriculture:  land_use_percents.agriculture,
            LandUseCategory.commercial:   land_use_percents.commercial,
            LandUseCategory.vacant:       land_use_percents.vacant,
        }

        breakdown: list[CategoryTaxResult] = []
        total_tax = 0.0
        notes: list[str] = []

        for cat, pct in pct_map.items():
            if pct <= 0:
                continue
            total_val = ctx.total_value_for_pct(pct)
            calc      = self._calc_category_tax(cat, total_val, ctx)
            total_tax += calc.tax_amount

            breakdown.append(CategoryTaxResult(
                category=       cat,
                category_label= CATEGORY_LABELS[cat],
                percent=        round(pct, 2),
                area_sqwah=     round(ctx.total_area_sqwah * pct / 100, 2),
                land_value=     round(ctx.land_value_for_pct(pct), 2),
                building_value= round(ctx.building_value_for_pct(pct), 2),
                total_value=    round(total_val, 2),
                tax_amount=     round(calc.tax_amount, 2),
                rate_label=     calc.rate_label + (
                    f" (+{calc.surcharge_note})" if calc.surcharge_note else ""
                ),
            ))

        # Notes
        notes.append("ประมาณการตาม พ.ร.บ. ภาษีที่ดินและสิ่งปลูกสร้าง พ.ศ. 2562 · อัตราปี 2569")
        vacant_breakdown = [b for b in breakdown if b.category == LandUseCategory.vacant]
        if vacant_breakdown:
            surcharge = self.calc_vacant_surcharge_rate(years_unused)
            if surcharge > 0:
                notes.append(
                    f"ที่ดินรกร้าง {years_unused} ปี → อัตราเพิ่ม {surcharge*100:.1f}% "
                    f"(ฐาน + {surcharge*100:.1f}%)"
                )
            else:
                notes.append(
                    f"ที่ดินรกร้างจะเพิ่มอัตรา 0.3% ทุก {self._cfg.vacant_land_increment_years} ปี "
                    f"สูงสุด {self._cfg.vacant_land_max_rate*100:.0f}%"
                )

        logger.info(
            "Tax calculated | area={} ตร.ว. | total_val={:,.0f} | tax={:,.0f} | years_unused={}",
            total_area_sqwah, ctx.total_property_value, total_tax, years_unused,
        )

        return TaxSummary(
            total_land_value=    round(ctx.total_land_value, 2),
            total_building_value=round(ctx.building_value_total, 2),
            total_property_value=round(ctx.total_property_value, 2),
            total_tax_per_year=  round(total_tax, 2),
            breakdown=breakdown,
            notes=notes,
        )

    # ── Per-category rules ────────────────────────────────────

    def _calc_category_tax(
        self, cat: LandUseCategory, total_val: float, ctx: AssessmentContext,
    ) -> _TaxCalcResult:
        if cat == LandUseCategory.agriculture:
            return self._tax_agriculture(total_val, ctx)
        elif cat == LandUseCategory.residential:
            return self._tax_residential(total_val, ctx)
        elif cat == LandUseCategory.commercial:
            return self._tax_commercial(total_val)
        elif cat == LandUseCategory.vacant:
            return self._tax_vacant(total_val, ctx.years_unused)
        return _TaxCalcResult(0.0, "ไม่ทราบประเภท")

    def _tax_agriculture(self, val: float, ctx: AssessmentContext) -> _TaxCalcResult:
        if ctx.is_individual:
            if val <= EXEMPT_50M:
                return _TaxCalcResult(0.0, "ยกเว้น (บุคคลธรรมดา ≤ 50 ล.)")
            tax   = calc_progressive_tax_from(val, AGRICULTURE_INDIVIDUAL_OVER_50M_BRACKETS, EXEMPT_50M)
            return _TaxCalcResult(tax, "0.01–0.10% (ส่วนเกิน 50 ล.)")
        else:
            tax   = calc_progressive_tax(val, AGRICULTURE_JURISTIC_BRACKETS)
            label = bracket_label_for(val, AGRICULTURE_JURISTIC_BRACKETS) + " (นิติบุคคล)"
            return _TaxCalcResult(tax, label)

    def _tax_residential(self, val: float, ctx: AssessmentContext) -> _TaxCalcResult:
        if ctx.is_primary_residence:
            if val <= EXEMPT_50M:
                return _TaxCalcResult(0.0, "ยกเว้น (หลักหลัก ≤ 50 ล.)")
            tax   = calc_progressive_tax_from(val, RESIDENTIAL_PRIMARY_OVER_50M_BRACKETS, EXEMPT_50M)
            return _TaxCalcResult(tax, "0.03–0.10% (ส่วนเกิน 50 ล.)")
        else:
            tax   = calc_progressive_tax(val, RESIDENTIAL_OTHER_BRACKETS)
            label = bracket_label_for(val, RESIDENTIAL_OTHER_BRACKETS)
            return _TaxCalcResult(tax, label)

    def _tax_commercial(self, val: float) -> _TaxCalcResult:
        tax   = calc_progressive_tax(val, COMMERCIAL_BRACKETS)
        label = bracket_label_for(val, COMMERCIAL_BRACKETS)
        return _TaxCalcResult(tax, label)

    def _tax_vacant(self, val: float, years_unused: int) -> _TaxCalcResult:
        """
        ที่ดินรกร้าง — คำนวณ progressive ก่อน แล้วบวก surcharge

        วิธีคิด:
        1. คำนวณภาษี base ตาม bracket (0.30–0.70%)
        2. คำนวณ surcharge_rate = floor(years/3) × 0.3% (cap ให้ total ≤ 3%)
        3. ภาษีรวม = (base_rate + surcharge_rate) × total_val
           หรือถ้า base_rate ใช้ progressive → บวก surcharge_rate × val เพิ่ม
        """
        base_tax  = calc_progressive_tax(val, VACANT_BRACKETS)
        base_label = bracket_label_for(val, VACANT_BRACKETS)

        surcharge_rate = self.calc_vacant_surcharge_rate(years_unused)

        if surcharge_rate <= 0:
            return _TaxCalcResult(
                base_tax,
                base_label,
                surcharge_note=None,
            )

        # Surcharge: คิดบน total value ทั้งก้อน (ไม่ progressive)
        # ภาษีรวม = base_progressive + surcharge_rate × val
        # แต่ cap ไว้ไม่เกิน 3% × val
        surcharge_tax = val * surcharge_rate
        total_tax     = min(base_tax + surcharge_tax, val * self._cfg.vacant_land_max_rate)

        periods = years_unused // self._cfg.vacant_land_increment_years
        effective_pct = min(
            (base_tax / val * 100) + (surcharge_rate * 100),
            self._cfg.vacant_land_max_rate * 100,
        )

        return _TaxCalcResult(
            total_tax,
            base_label,
            surcharge_note=(
                f"ปล่อยรกร้าง {years_unused} ปี "
                f"→ +{surcharge_rate*100:.1f}% surcharge "
                f"({periods} รอบ × 0.3%) "
                f"อัตรารวมประมาณ {effective_pct:.2f}%"
            ),
        )