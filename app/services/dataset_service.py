"""Veri seti kullanim senaryolari.

Yukleme, listeleme ve analitik hesaplama. Bu katman cerceveyi (FastAPI) degil,
yalnizca domain ve repository'leri bilir.
"""

from __future__ import annotations

import csv
import hashlib
import io
import logging
import uuid
from collections import OrderedDict
from dataclasses import dataclass
from pathlib import Path

from app.core.config import Settings
from app.core.errors import EmptyDatasetError, FileTooLargeError, NotFoundError
from app.domain.analytics.engine import analyze
from app.domain.models import AnalyticsResult, QualityReport
from app.domain.packs.base import DatasetPack
from app.domain.quality.encoding import decode_bytes
from app.domain.quality.pipeline import ingest
from app.services.registry import detect_pack, get_pack
from app.storage.models import Dataset
from app.storage.repositories import DatasetRepository

_log = logging.getLogger(__name__)

_ANALYTICS_MEMO: OrderedDict[str, tuple[AnalyticsResult, QualityReport]] = OrderedDict()
_MEMO_LIMIT = 16
"""Surec ici LRU. Satir verisini kalici saklamadigimiz icin her istekte CSV
yeniden okunuyor; bu bellek onbellegi ayni veri seti icin tekrari onler.
Islem milisaniyeler surdugunden onbellek kucuk tutuluyor."""


@dataclass(slots=True)
class LoadedDataset:
    record: Dataset
    pack: DatasetPack
    analytics: AnalyticsResult
    quality: QualityReport


class DatasetService:
    def __init__(self, repository: DatasetRepository, settings: Settings) -> None:
        self._repository = repository
        self._settings = settings

    # -- yukleme ----------------------------------------------------------
    async def create(self, raw: bytes, filename: str, pack_key: str | None) -> LoadedDataset:
        if len(raw) > self._settings.max_upload_bytes:
            raise FileTooLargeError(
                f"Dosya {len(raw) / 1_048_576:.1f} MB; sinir "
                f"{self._settings.max_upload_bytes / 1_048_576:.0f} MB.",
            )
        if not raw.strip():
            raise EmptyDatasetError("Yuklenen dosya bos.")

        pack = get_pack(pack_key) if pack_key else self._detect(raw)
        outcome = ingest(raw, pack)

        content_hash = hashlib.sha256(raw).hexdigest()
        dataset_id = uuid.uuid4().hex[:16]
        stored_path = self._settings.upload_dir / f"{dataset_id}.csv"
        stored_path.write_bytes(raw)

        record = await self._repository.add(
            Dataset(
                id=dataset_id,
                filename=Path(filename).name,
                pack_key=pack.key,
                content_hash=content_hash,
                stored_path=str(stored_path),
                raw_row_count=outcome.report.raw_row_count,
                clean_row_count=outcome.report.clean_row_count,
                quarantined_row_count=outcome.report.quarantined_row_count,
                health_score=outcome.report.health_score,
                encoding_detected=outcome.report.encoding_detected,
                quality_json=_dump(outcome.report),
            )
        )

        analytics = analyze(outcome.clean, pack)
        _memoize(content_hash, pack.key, analytics, outcome.report)
        _log.info(
            "dataset_created",
            extra={
                "dataset_id": dataset_id,
                "pack": pack.key,
                "rows": outcome.report.clean_row_count,
                "health": outcome.report.health_score,
                "risks": len(analytics.risks),
            },
        )
        return LoadedDataset(record, pack, analytics, outcome.report)

    def _detect(self, raw: bytes) -> DatasetPack:
        text = decode_bytes(raw).text
        reader = csv.reader(io.StringIO(text))
        headers = next(reader, [])
        pack = detect_pack([h.strip() for h in headers])
        if pack is None:
            raise EmptyDatasetError(
                "Dosyanin hangi rapor tipine ait oldugu anlasilamadi. "
                "Yuklerken 'pack' parametresini acikca belirtin.",
            )
        return pack

    # -- okuma ------------------------------------------------------------
    async def list(self) -> list[Dataset]:
        return await self._repository.list()

    async def get_record(self, dataset_id: str) -> Dataset:
        record = await self._repository.get(dataset_id)
        if record is None:
            raise NotFoundError(f"'{dataset_id}' kimlikli veri seti bulunamadi.")
        return record

    async def load(self, dataset_id: str) -> LoadedDataset:
        """Kayittan tam analiz sonucunu uretir (onbellekliyse yeniden hesaplamaz)."""
        record = await self.get_record(dataset_id)
        pack = get_pack(record.pack_key)

        cached = _lookup(record.content_hash, pack.key)
        if cached is not None:
            analytics, quality = cached
            return LoadedDataset(record, pack, analytics, quality)

        path = Path(record.stored_path)
        if not path.exists():
            raise NotFoundError(
                "Veri setinin ham dosyasi diskte bulunamadi; yeniden yukleyin.",
                details={"dataset_id": dataset_id},
            )

        outcome = ingest(path.read_bytes(), pack)
        analytics = analyze(outcome.clean, pack)
        _memoize(record.content_hash, pack.key, analytics, outcome.report)
        return LoadedDataset(record, pack, analytics, outcome.report)

    async def delete(self, dataset_id: str) -> None:
        record = await self.get_record(dataset_id)
        Path(record.stored_path).unlink(missing_ok=True)
        await self._repository.delete(dataset_id)


# ---------------------------------------------------------------------------
def _memo_key(content_hash: str, pack_key: str) -> str:
    return f"{pack_key}:{content_hash}"


def _memoize(
    content_hash: str, pack_key: str, analytics: AnalyticsResult, quality: QualityReport
) -> None:
    key = _memo_key(content_hash, pack_key)
    _ANALYTICS_MEMO[key] = (analytics, quality)
    _ANALYTICS_MEMO.move_to_end(key)
    while len(_ANALYTICS_MEMO) > _MEMO_LIMIT:
        _ANALYTICS_MEMO.popitem(last=False)


def _lookup(content_hash: str, pack_key: str) -> tuple[AnalyticsResult, QualityReport] | None:
    key = _memo_key(content_hash, pack_key)
    if key not in _ANALYTICS_MEMO:
        return None
    _ANALYTICS_MEMO.move_to_end(key)
    return _ANALYTICS_MEMO[key]


def _dump(report: QualityReport) -> str:
    import json

    return json.dumps(report.to_dict(), ensure_ascii=False)
