"""Repository katmani.

Servisler SQLAlchemy'yi dogrudan gormez; sorgu detaylari burada kapali kalir.
Boylece depolama degistiginde (Postgres, farkli bir sema) servis katmani
dokunulmadan kalir.
"""

from __future__ import annotations

import json
from typing import Any

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.storage.models import AICacheEntry, Dataset


class DatasetRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def add(self, dataset: Dataset) -> Dataset:
        self._session.add(dataset)
        await self._session.commit()
        await self._session.refresh(dataset)
        return dataset

    async def get(self, dataset_id: str) -> Dataset | None:
        return await self._session.get(Dataset, dataset_id)

    async def list(self, limit: int = 50) -> list[Dataset]:
        stmt = select(Dataset).order_by(Dataset.created_at.desc()).limit(limit)
        return list((await self._session.scalars(stmt)).all())

    async def find_by_hash(self, content_hash: str, pack_key: str) -> Dataset | None:
        stmt = select(Dataset).where(
            Dataset.content_hash == content_hash, Dataset.pack_key == pack_key
        )
        return (await self._session.scalars(stmt)).first()

    async def delete(self, dataset_id: str) -> None:
        await self._session.execute(delete(Dataset).where(Dataset.id == dataset_id))
        await self._session.execute(
            delete(AICacheEntry).where(AICacheEntry.dataset_id == dataset_id)
        )
        await self._session.commit()


class AICacheRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get(self, cache_key: str) -> dict[str, Any] | None:
        stmt = select(AICacheEntry).where(AICacheEntry.cache_key == cache_key)
        entry = (await self._session.scalars(stmt)).first()
        if entry is None:
            return None
        payload: dict[str, Any] = json.loads(entry.payload_json)
        payload["_cached"] = True
        payload["_cached_at"] = entry.created_at.isoformat()
        return payload

    async def put(
        self,
        *,
        cache_key: str,
        dataset_id: str,
        kind: str,
        payload: dict[str, Any],
        grounding_ratio: float = 0.0,
        cost_usd: float = 0.0,
    ) -> None:
        # Ayni anahtar varsa tazele (prompt surumu anahtarda oldugu icin
        # bu yalnizca yeniden uretim istendiginde olur).
        await self._session.execute(delete(AICacheEntry).where(AICacheEntry.cache_key == cache_key))
        self._session.add(
            AICacheEntry(
                cache_key=cache_key,
                dataset_id=dataset_id,
                kind=kind,
                payload_json=json.dumps(payload, ensure_ascii=False, default=str),
                grounding_ratio=grounding_ratio,
                cost_usd=cost_usd,
            )
        )
        await self._session.commit()

    async def invalidate_dataset(self, dataset_id: str) -> None:
        await self._session.execute(
            delete(AICacheEntry).where(AICacheEntry.dataset_id == dataset_id)
        )
        await self._session.commit()
