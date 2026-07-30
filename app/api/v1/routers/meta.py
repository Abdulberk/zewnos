"""Saglik ve yetenek uclari."""

from __future__ import annotations

from fastapi import APIRouter

from app.api.deps import SettingsDep
from app.api.mappers import pack_out
from app.api.responses import COMMON_ERRORS
from app.schemas.common import PackOut
from app.services.registry import list_packs

router = APIRouter(tags=["meta"], responses=COMMON_ERRORS)


@router.get("/health", summary="Servis ayakta mı")
async def health() -> dict[str, str]:
    return {"status": "ok"}


@router.get("/health/ready", summary="Bağımlılıklar hazır mı")
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
    summary="Tanımlı rapor tipleri",
    description=(
        "Her kayıt bir 'dataset pack'. Yeni bir rapor tipi eklemek için motora, "
        "endpoint'lere veya AI katmanına dokunmak gerekmez -- yalnızca yeni bir "
        "pack tanımlanıp buraya kaydedilir."
    ),
)
async def packs() -> list[PackOut]:
    return [pack_out(p) for p in list_packs()]
