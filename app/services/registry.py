"""Dataset pack kayit defteri.

Yeni bir rapor tipi eklemek = bir pack yazip buraya kaydetmek. Motor, API
uclari ve AI katmani degismez. "300+ raporu tek dashboard'a tasima" hedefinin
kod tarafindaki karsiligi bu dosyanin kisaligidir.
"""

from __future__ import annotations

from app.core.errors import UnknownPackError
from app.domain.packs.base import DatasetPack
from app.domain.packs.sonart_erp import PACK as SONART_ERP
from app.domain.packs.zewnos_ads import PACK as ZEWNOS_ADS

_PACKS: dict[str, DatasetPack] = {
    SONART_ERP.key: SONART_ERP,
    ZEWNOS_ADS.key: ZEWNOS_ADS,
}

DEFAULT_PACK_KEY = SONART_ERP.key


def get_pack(key: str) -> DatasetPack:
    pack = _PACKS.get(key)
    if pack is None:
        raise UnknownPackError(
            f"'{key}' adinda bir veri seti tipi tanimli degil.",
            details={"available": sorted(_PACKS)},
        )
    return pack


def list_packs() -> list[DatasetPack]:
    return list(_PACKS.values())


def detect_pack(headers: list[str]) -> DatasetPack | None:
    """Basliklara bakarak hangi pack oldugunu tahmin eder.

    Kullanici pack secmeden dosya yukleyebilsin diye. Zorunlu kolonlarinin
    tamami eslesen ilk pack secilir; hicbiri eslesmezse None doner ve
    kullanicidan acikca secim istenir.
    """
    for pack in _PACKS.values():
        _, missing = pack.resolve_headers(headers)
        if not missing:
            return pack
    return None
