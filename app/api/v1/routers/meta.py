"""Saglik ve yetenek uclari."""

from __future__ import annotations

from fastapi import APIRouter

from app.api.deps import SettingsDep
from app.api.mappers import pack_out
from app.schemas.common import PackOut
from app.services.registry import list_packs

router = APIRouter(tags=["meta"])


@router.get("/health", summary="Servis ayakta mi")
async def health() -> dict[str, str]:
    return {"status": "ok"}


@router.get("/health/ready", summary="Bagimliliklar hazir mi")
async def ready(settings: SettingsDep) -> dict[str, object]:
    return {
        "status": "ok",
        "ai_configured": settings.ai_configured,
        "ai_model": settings.ai_model,
        "ai_effort": settings.ai_effort,
        "packs": [p.key for p in list_packs()],
    }


@router.get(
    "/packs",
    response_model=list[PackOut],
    summary="Tanimli rapor tipleri",
    description=(
        "Her kayit bir 'dataset pack'. Yeni bir rapor tipi eklemek icin motora, "
        "endpoint'lere veya AI katmanina dokunmak gerekmez -- yalnizca yeni bir "
        "pack tanimlanip buraya kaydedilir."
    ),
)
async def packs() -> list[PackOut]:
    return [pack_out(p) for p in list_packs()]
