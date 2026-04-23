"""
───────────────────────────────
CRUD operations สำหรับ LandParcel
"""
from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.parcel import LandParcel


class ParcelService:

    @staticmethod
    async def create(session: AsyncSession, data: dict) -> LandParcel:
        parcel = LandParcel()
        for k, v in data.items():
            if hasattr(parcel, k):
                setattr(parcel, k, v)
        session.add(parcel)
        await session.commit()
        await session.refresh(parcel)
        return parcel

    @staticmethod
    async def get_all(session: AsyncSession) -> list[LandParcel]:
        result = await session.execute(
            select(LandParcel).order_by(LandParcel.created_at.desc())
        )
        return result.scalars().all()

    @staticmethod
    async def get_by_id(session: AsyncSession, parcel_id: int) -> LandParcel | None:
        return await session.get(LandParcel, parcel_id)

    @staticmethod
    async def update(session: AsyncSession, parcel_id: int, data: dict) -> LandParcel | None:
        parcel = await session.get(LandParcel, parcel_id)
        if not parcel:
            return None
        for k, v in data.items():
            if hasattr(parcel, k):
                setattr(parcel, k, v)
        await session.commit()
        await session.refresh(parcel)
        return parcel

    @staticmethod
    async def delete(session: AsyncSession, parcel_id: int) -> bool:
        parcel = await session.get(LandParcel, parcel_id)
        if not parcel:
            return False
        await session.delete(parcel)
        await session.commit()
        return True