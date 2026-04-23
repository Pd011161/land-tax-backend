"""
ดึงภาพดาวเทียมจาก Google Maps Static API
"""
from __future__ import annotations

import base64
import time

import httpx
from loguru import logger

from app.api.types.schemas import MapImageResponse
from app.core.config import GoogleMapsConfig

GOOGLE_MAPS_STATIC_URL = "https://maps.googleapis.com/maps/api/staticmap"


class MapService:
    def __init__(self, config: GoogleMapsConfig) -> None:
        self._config = config
        self._client = httpx.AsyncClient(timeout=30.0)
        logger.info("MapService initialized")

    async def fetch_satellite_image(
        self,
        lat: float,
        lon: float,
        zoom: int | None = None,
    ) -> MapImageResponse:
        """
        ดึงภาพดาวเทียมจาก Google Maps Static API

        Returns
        -------
        MapImageResponse
            image_base64 พร้อม metadata
        """
        if not self._config.api_key:
            raise ValueError(
                "GOOGLE_MAPS_KEY ยังไม่ได้ตั้งค่า — กรุณาเพิ่มใน environment variable"
            )

        zoom = zoom or self._config.default_zoom
        t0   = time.perf_counter()

        params = {
            "center":   f"{lat},{lon}",
            "zoom":     zoom,
            "size":     self._config.image_size,
            "maptype":  self._config.map_type,
            "key":      self._config.api_key,
        }

        logger.info("Fetching satellite map | lat={} lon={} zoom={}", lat, lon, zoom)

        try:
            response = await self._client.get(GOOGLE_MAPS_STATIC_URL, params=params)
            response.raise_for_status()

            mime_type    = response.headers.get("content-type", "image/png").split(";")[0]
            image_bytes  = response.content
            image_base64 = base64.b64encode(image_bytes).decode("utf-8")

            elapsed = time.perf_counter() - t0
            logger.info(
                "Map image fetched | size={} bytes | elapsed={:.2f}s",
                len(image_bytes),
                elapsed,
            )

            return MapImageResponse(
                image_base64=image_base64,
                image_mime=mime_type,
                lat=lat,
                lon=lon,
                zoom=zoom,
            )

        except httpx.HTTPStatusError as exc:
            logger.error("Google Maps API error: {} {}", exc.response.status_code, exc.response.text[:200])
            raise ValueError(
                f"Google Maps API ตอบกลับ {exc.response.status_code} — "
                "ตรวจสอบ API Key และว่าได้เปิดใช้ Maps Static API หรือยัง"
            ) from exc

        except httpx.RequestError as exc:
            logger.error("Network error fetching map: {}", exc)
            raise ValueError(f"เชื่อมต่อ Google Maps ไม่ได้: {exc}") from exc

    async def close(self) -> None:
        await self._client.aclose()
