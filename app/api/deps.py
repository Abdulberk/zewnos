"""Bagimlilik enjeksiyonu.

FastAPI'nin `Depends` mekanizmasini kullaniyoruz -- ucuncu parti bir DI
container'a gerek yok. Baglama acik ve okunabilir fonksiyonlarla yapiliyor;
testte tek satirla override edilebiliyor (`app.dependency_overrides`).
"""

from __future__ import annotations

from typing import Annotated

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings, get_settings
from app.services.analysis_service import AnalysisService
from app.services.dataset_service import DatasetService, LoadedDataset
from app.storage.db import get_session
from app.storage.repositories import AICacheRepository, DatasetRepository

SettingsDep = Annotated[Settings, Depends(get_settings)]
SessionDep = Annotated[AsyncSession, Depends(get_session)]


def get_dataset_service(session: SessionDep, settings: SettingsDep) -> DatasetService:
    return DatasetService(DatasetRepository(session), settings)


def get_analysis_service(session: SessionDep, settings: SettingsDep) -> AnalysisService:
    return AnalysisService(AICacheRepository(session), settings)


DatasetServiceDep = Annotated[DatasetService, Depends(get_dataset_service)]
AnalysisServiceDep = Annotated[AnalysisService, Depends(get_analysis_service)]


async def get_loaded_dataset(dataset_id: str, service: DatasetServiceDep) -> LoadedDataset:
    """Yol parametresindeki kimlikten tam analiz sonucunu yukler."""
    return await service.load(dataset_id)


LoadedDatasetDep = Annotated[LoadedDataset, Depends(get_loaded_dataset)]
