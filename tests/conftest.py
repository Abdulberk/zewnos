"""Ortak test fikstürleri."""

from __future__ import annotations

from pathlib import Path

import polars as pl
import pytest

from app.domain.analytics.engine import analyze
from app.domain.models import AnalyticsResult
from app.domain.packs.base import DatasetPack
from app.domain.packs.sonart_erp import PACK as SONART_PACK
from app.domain.packs.zewnos_ads import PACK as ADS_PACK
from app.domain.quality.pipeline import IngestOutcome, ingest

SAMPLES = Path(__file__).resolve().parents[1] / "data" / "samples"


def to_mojibake(text: str) -> str:
    """Dogru UTF-8 metni, CP1252 olarak okunmus haline cevirir.

    Gercek bozulmanin kayipsiz simulasyonu: testin onarim yolunu deterministik
    olarak dogrulayabilmesi icin.
    """
    return text.encode("utf-8").decode("cp1252")


@pytest.fixture(scope="session")
def sonart_pack() -> DatasetPack:
    return SONART_PACK


@pytest.fixture(scope="session")
def ads_pack() -> DatasetPack:
    return ADS_PACK


@pytest.fixture(scope="session")
def sonart_bytes() -> bytes:
    return (SAMPLES / "sonart_erp_cok_donemli.csv").read_bytes()


@pytest.fixture(scope="session")
def ads_bytes() -> bytes:
    return (SAMPLES / "zewnos_meta_ads_cok_donemli.csv").read_bytes()


@pytest.fixture(scope="session")
def sonart_ingest(sonart_bytes: bytes, sonart_pack: DatasetPack) -> IngestOutcome:
    return ingest(sonart_bytes, sonart_pack)


@pytest.fixture(scope="session")
def sonart_result(sonart_ingest: IngestOutcome, sonart_pack: DatasetPack) -> AnalyticsResult:
    return analyze(sonart_ingest.clean, sonart_pack)


@pytest.fixture(scope="session")
def ads_result(ads_bytes: bytes, ads_pack: DatasetPack) -> AnalyticsResult:
    outcome = ingest(ads_bytes, ads_pack)
    return analyze(outcome.clean, ads_pack)


def entity_row(result: AnalyticsResult, entity: str, key: str = "stok_kodu") -> dict:
    for row in result.entity_rows:
        if row.get(key) == entity:
            return row
    raise AssertionError(f"{entity} entity ozetinde bulunamadi")


def series_value(
    clean: pl.DataFrame, entity: str, period: str, column: str, key: str = "stok_kodu"
):
    row = clean.filter((pl.col(key) == entity) & (pl.col("donem") == period))
    assert row.height == 1, f"{entity}/{period} icin tek satir bekleniyordu, {row.height} bulundu"
    return row.get_column(column).item()


def risk_codes(result: AnalyticsResult, entity: str) -> set[str]:
    return {r.code for r in result.risks if r.entity == entity}
