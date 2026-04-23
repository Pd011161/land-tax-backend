"""
──────────────────
Pydantic Settings — loads from config.yaml + env vars.
Priority: env var > config.yaml

Authentication สำหรับ Vertex AI:
  VERTEX_SA_JSON_PATH  → path ไปยังไฟล์ service account JSON (local dev)
  VERTEX_SA_JSON       → JSON string ทั้งก้อน (Docker / K8s secrets)
  VERTEX_PROJECT       → Google Cloud Project ID
  VERTEX_LOCATION      → region (default: us-central1)

CORS:
  CORS_ALLOW_ALL=true  → เปิด * (dev only — ไม่ใช้ใน production)
"""
from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path

import yaml
from pydantic import Field, field_validator
from pydantic_settings import BaseSettings
from dotenv import load_dotenv

load_dotenv()

def _load_yaml(path: Path) -> dict:
    if not path.exists():
        return {}
    with open(path) as f:
        return yaml.safe_load(f) or {}


# ── Sub-configs ───────────────────────────────────────────────

class AppConfig(BaseSettings):
    name: str = "Land Tax API"
    version: str = "1.0.0"
    host: str = "0.0.0.0"
    port: int = 8000
    # ถ้า CORS_ALLOW_ALL=true → override เป็น ["*"] ตอน get_settings()
    cors_origins: list[str] = ["http://localhost:5500", "http://127.0.0.1:5500"]

    model_config = {"extra": "ignore"}


class VertexAIConfig(BaseSettings):
    """
    Google Vertex AI — Gemini 2.5 Flash Vision via LangChain.

    Authentication (เลือกอย่างใดอย่างหนึ่ง):
      VERTEX_SA_JSON_PATH  → path ไปยังไฟล์ .json  (แนะนำสำหรับ local dev)
      VERTEX_SA_JSON       → JSON string ทั้งก้อน   (Docker / K8s secret)
    """
    sa_json_path: str = Field(default="", alias="VERTEX_SA_JSON_PATH")
    sa_json:      str = Field(default="", alias="VERTEX_SA_JSON")

    project:  str = Field(default="", alias="VERTEX_PROJECT")
    location: str = Field(default="us-central1", alias="VERTEX_LOCATION")

    model:       str   = "gemini-2.5-flash"
    max_tokens:  int   = 6512
    temperature: float = 0.0
    timeout:     int   = 60

    model_config = {"extra": "ignore", "populate_by_name": True}


class GoogleMapsConfig(BaseSettings):
    api_key: str = Field(default="", alias="GOOGLE_MAPS_KEY")
    map_type: str = "satellite"
    image_size: str = "640x480"
    default_zoom: int = 18

    model_config = {"extra": "ignore", "populate_by_name": True}


class TaxConfig(BaseSettings):
    default_land_price_per_sqwah: float = 10_000
    vacant_land_increment_years: int = 3
    vacant_land_max_rate: float = 0.03

    model_config = {"extra": "ignore"}

class Settings(BaseSettings):
    app:         AppConfig       = AppConfig()
    vertex_ai:   VertexAIConfig  = VertexAIConfig()
    google_maps: GoogleMapsConfig = GoogleMapsConfig()
    tax:         TaxConfig       = TaxConfig()
    database_url: str = Field(
        # default="postgresql+asyncpg://postgres:com011161@localhost:5432/landtax",
        default="postgresql+asyncpg://postgres:password@db:5432/landtax",
        alias="DATABASE_URL",
    )

    model_config = {"extra": "ignore", "populate_by_name": True}


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """
    Load settings from config.yaml then overlay env vars.

    CORS shortcut:
      CORS_ALLOW_ALL=true  → allow all origins (dev/testing only)
    """
    root = Path(__file__).parent.parent.parent
    yaml_data = _load_yaml(root / "config" / "config.yaml")

    # ── CORS ─────────────────────────────────────────────────
    app_data = yaml_data.get("app", {})

    if os.getenv("CORS_ALLOW_ALL", "").lower() in ("true", "1", "yes"):
        # Dev shortcut: allow everything
        app_data["cors_origins"] = ["*"]

    elif os.getenv("CORS_EXTRA_ORIGINS"):
        # เพิ่ม origins จาก env (comma-separated) เข้าไปใน whitelist
        # ใช้ชื่อ CORS_EXTRA_ORIGINS เพื่อไม่ conflict กับ Pydantic Settings
        extra = [o.strip() for o in os.getenv("CORS_EXTRA_ORIGINS").split(",") if o.strip()]
        existing = app_data.get("cors_origins", [])
        app_data["cors_origins"] = list(dict.fromkeys(existing + extra))

    # ── Vertex AI ────────────────────────────────────────────
    vertex_data = yaml_data.get("vertex_ai", {})
    vertex_data.setdefault("VERTEX_SA_JSON_PATH", os.getenv("VERTEX_SA_JSON_PATH", ""))
    vertex_data.setdefault("VERTEX_SA_JSON",      os.getenv("VERTEX_SA_JSON", ""))
    vertex_data.setdefault("VERTEX_PROJECT",      os.getenv("VERTEX_PROJECT", ""))
    vertex_data.setdefault("VERTEX_LOCATION",     os.getenv("VERTEX_LOCATION", "us-central1"))

    # ── Google Maps ──────────────────────────────────────────
    gmap_data = yaml_data.get("google_maps", {})
    gmap_data["GOOGLE_MAPS_KEY"] = os.getenv(
        "GOOGLE_MAPS_KEY", gmap_data.pop("api_key", "")
    )

    return Settings(
        app=         AppConfig(**app_data),
        vertex_ai=   VertexAIConfig(**vertex_data),
        google_maps= GoogleMapsConfig(**gmap_data),
        tax=         TaxConfig(**yaml_data.get("tax", {})),
    )