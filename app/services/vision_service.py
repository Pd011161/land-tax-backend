"""
──────────────────────────────
วิเคราะห์ภาพที่ดินด้วย LangChain + Gemini 2.5 Flash

Auth: Google Service Account JSON → google.oauth2.service_account.Credentials
LLM:  ChatGoogleGenerativeAI (langchain-google-genai) พร้อม credentials object
      ใช้ json_schema structured output + include_raw=True เพื่อ debug ได้

หมายเหตุ: ChatVertexAI deprecated ใน LangChain 3.2 → ใช้ ChatGoogleGenerativeAI แทน
แต่ยังคง auth ด้วย Service Account JSON เหมือนเดิม (ไม่ใช้ GOOGLE_API_KEY)
"""
from __future__ import annotations

import json
import time
from pathlib import Path

from langchain_core.messages import HumanMessage, SystemMessage
from langchain_google_genai import ChatGoogleGenerativeAI
from loguru import logger
from pydantic import BaseModel, Field

from app.api.types.schemas import LandUseAnalysisResult, LandUsePercents
from app.core.config import VertexAIConfig

# ── Structured output schema ──────────────────────────────────

class LandUseRaw(BaseModel):
    """Target schema สำหรับ LangChain with_structured_output()"""
    residential: float = Field(ge=0, le=100, description="% ที่อยู่อาศัย บ้าน อาคาร")
    agriculture:  float = Field(ge=0, le=100, description="% เกษตรกรรม นาข้าว สวน ไร่")
    commercial:   float = Field(ge=0, le=100, description="% พาณิชยกรรม ร้านค้า โรงงาน")
    vacant:       float = Field(ge=0, le=100, description="% รกร้างว่างเปล่า ที่ดินไม่ได้ใช้")
    note:         str   = Field(description="หมายเหตุสั้น ๆ ภาษาไทย ไม่เกิน 50 คำ")

# ── Prompts ───────────────────────────────────────────────────

SYSTEM_PROMPT = (
    "คุณคือผู้เชี่ยวชาญด้านการวิเคราะห์ภาพถ่ายดาวเทียมและการประเมินการใช้ที่ดินในประเทศไทย "
    "วิเคราะห์ภาพอย่างละเอียดและตอบตาม schema ที่กำหนดเท่านั้น"
)

HUMAN_TEMPLATE = """\
วิเคราะห์ภาพที่ดินนี้และประมาณสัดส่วนการใช้ที่ดินเป็นเปอร์เซ็นต์
{boundary_instruction}
{context}

กฎสำคัญ: residential + agriculture + commercial + vacant ต้องรวมกันได้ 100 พอดี
"""


def _load_credentials(config: VertexAIConfig):
    """
    โหลด Google Service Account credentials จาก config.

    Priority:
    1. VERTEX_SA_JSON_PATH  → อ่านจากไฟล์ .json
    2. VERTEX_SA_JSON       → parse จาก JSON string โดยตรง
    3. None                 → Application Default Credentials (ADC)
    """
    from google.oauth2 import service_account

    scopes = ["https://www.googleapis.com/auth/cloud-platform"]

    if config.sa_json_path:
        path = Path(config.sa_json_path)
        if not path.exists():
            raise FileNotFoundError(
                f"Service account JSON ไม่พบที่ {path} — ตรวจสอบ VERTEX_SA_JSON_PATH"
            )
        logger.info("Loading Vertex AI credentials from file | path={}", path)
        return service_account.Credentials.from_service_account_file(
            str(path), scopes=scopes
        )

    if config.sa_json:
        logger.info("Loading Vertex AI credentials from inline JSON string")
        info = json.loads(config.sa_json)
        return service_account.Credentials.from_service_account_info(
            info, scopes=scopes
        )

    logger.warning(
        "ไม่พบ VERTEX_SA_JSON_PATH หรือ VERTEX_SA_JSON — "
        "ใช้ Application Default Credentials"
    )
    return None


class VisionService:
    """
    Lazy-init: LangChain chain สร้างตอน first call
    เพื่อให้ startup ไม่ fail เมื่อยังไม่มี credentials (เช่น unit test)
    """

    def __init__(self, config: VertexAIConfig) -> None:
        self._config = config
        self._chain  = None
        logger.info(
            "VisionService initialized | provider=Gemini (SA auth) | model={} | project={}",
            config.model, config.project or "(default)",
        )

    def _get_chain(self):
        """Build ChatGoogleGenerativeAI + structured output chain (cached)."""
        if self._chain is not None:
            return self._chain

        credentials = _load_credentials(self._config)

        # ChatGoogleGenerativeAI รับ credentials object โดยตรง
        # ไม่ต้องใช้ google_api_key เมื่อมี service account credentials
        llm = ChatGoogleGenerativeAI(
            model=self._config.model,
            credentials=credentials,          # SA credentials แทน API key
            temperature=self._config.temperature,
            max_output_tokens=self._config.max_tokens,
            timeout=self._config.timeout,
        )

        # method="json_schema" — ใช้ native JSON schema support ของ Gemini
        # include_raw=True — ถ้า parse ล้มเหลว เราจะเห็น raw response แทน None
        self._chain = llm.with_structured_output(
            LandUseRaw,
            method="json_schema",
            include_raw=True,
        )

        logger.info(
            "LangChain chain built | model={} | project={} | method=json_schema",
            self._config.model, self._config.project,
        )
        return self._chain

    async def analyze_land_use(
        self,
        image_base64: str,
        image_mime: str = "image/jpeg",
        context: str | None = None,
        has_drawn_boundary: bool = True,
    ) -> LandUseAnalysisResult:
        """
        วิเคราะห์ภาพ → คืน LandUseAnalysisResult พร้อม percents

        Parameters
        ----------
        image_base64 : str    Base64 encoded image (merged bg + drawing layer)
        image_mime : str      MIME type (image/jpeg, image/png, image/webp)
        context : str | None  บริบทเพิ่มเติมที่ user ระบุ
        has_drawn_boundary    True = มีเส้นสีแดงล้อมรอบพื้นที่ที่ต้องการ
        """
        t0 = time.perf_counter()

        boundary_instruction = (
            "สำคัญ: วิเคราะห์เฉพาะพื้นที่ภายในเส้นสีแดงที่ผู้ใช้วาดล้อมรอบเท่านั้น "
            "ละเว้นพื้นที่ที่ดินแปลงอื่นนอกเส้น"
            if has_drawn_boundary else ""
        )
        context_line = f"บริบทเพิ่มเติม: {context}" if context else ""

        human_text = HUMAN_TEMPLATE.format(
            boundary_instruction=boundary_instruction,
            context=context_line,
        ).strip()

        messages = [
            SystemMessage(content=SYSTEM_PROMPT),
            HumanMessage(content=[
                {
                    "type": "image_url",
                    "image_url": {
                        "url": f"data:{image_mime};base64,{image_base64}",
                    },
                },
                {"type": "text", "text": human_text},
            ]),
        ]

        try:
            chain = self._get_chain()

            # include_raw=True → response = {"raw": AIMessage, "parsed": LandUseRaw | None}
            response: dict = await chain.ainvoke(messages)

            raw_ai_msg = response.get("raw")
            parsed: LandUseRaw | None = response.get("parsed")

            elapsed = time.perf_counter() - t0

            if parsed is None:
                # Structured output parse ล้มเหลว — log raw response แล้ว fallback
                raw_text = getattr(raw_ai_msg, "content", str(raw_ai_msg))
                logger.warning(
                    "Structured output returned None after {:.2f}s | "
                    "raw response: {}",
                    elapsed, raw_text[:300],
                )
                raise ValueError(
                    f"Gemini returned unparseable response: {raw_text[:200]}"
                )

            logger.info(
                "Vision analysis done | elapsed={:.2f}s | model={} | "
                "res={:.0f}% agr={:.0f}% com={:.0f}% vac={:.0f}%",
                elapsed, self._config.model,
                parsed.residential, parsed.agriculture,
                parsed.commercial, parsed.vacant,
            )

            percents = LandUsePercents(
                residential=parsed.residential,
                agriculture= parsed.agriculture,
                commercial=  parsed.commercial,
                vacant=      parsed.vacant,
            ).normalize()

            return LandUseAnalysisResult(
                percents=percents,
                source="ai",
                ai_note=parsed.note or None,
                model_used=self._config.model,
            )

        except Exception as exc:
            elapsed = time.perf_counter() - t0
            logger.error(
                "Vision analysis failed after {:.2f}s | {}: {}",
                elapsed, type(exc).__name__, exc,
            )
            fallback = LandUsePercents(
                residential=40, agriculture=30, commercial=20, vacant=10
            )
            return LandUseAnalysisResult(
                percents=fallback,
                source="ai_fallback",
                ai_note=f"วิเคราะห์ไม่สำเร็จ ({type(exc).__name__}) ใช้ค่าเริ่มต้น กรุณาแก้ไข %",
                model_used=self._config.model,
            )