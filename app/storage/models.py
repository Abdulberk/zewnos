"""Kalici veri modelleri.

Yalnizca iki tablo tutuyoruz:

  datasets  -- yuklenen dosyanin kimligi ve kalite ozeti
  ai_cache  -- uretilmis AI analizleri

Satir verisi kasten saklanmiyor: ham CSV diskte duruyor ve her istekte Polars
ile yeniden hesaplaniyor. Bu veri buyuklugunde (binlerce satir) yeniden hesap
milisaniyeler suruyor ve analitik mantigin tek kaynagi kod olarak kaliyor --
SQL ile Polars arasinda bolunmuyor.

ai_cache ise gercekten gerekli: onbellek olmadan her dashboard yenilemesi
7 Claude cagrisi demek -- demo yavas, maliyet bosa, ekran goruntuleri arasi
cikti degisken olurdu.
"""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import DateTime, Float, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.storage.db import Base


def _utcnow() -> datetime:
    return datetime.now(UTC)


class Dataset(Base):
    __tablename__ = "datasets"

    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    filename: Mapped[str] = mapped_column(String(255))
    pack_key: Mapped[str] = mapped_column(String(64), index=True)
    content_hash: Mapped[str] = mapped_column(String(64), index=True)
    stored_path: Mapped[str] = mapped_column(String(512))

    raw_row_count: Mapped[int] = mapped_column(Integer, default=0)
    clean_row_count: Mapped[int] = mapped_column(Integer, default=0)
    quarantined_row_count: Mapped[int] = mapped_column(Integer, default=0)
    health_score: Mapped[int] = mapped_column(Integer, default=0)
    encoding_detected: Mapped[str] = mapped_column(String(64), default="")

    quality_json: Mapped[str] = mapped_column(Text, default="{}")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)


class AICacheEntry(Base):
    """Uretilmis AI ciktisi.

    Anahtar: dosya icerigi + pack + prompt surumu + model + cagri tipi.
    Prompt surumu anahtara dahil cunku prompt degistiginde eski cikti
    gecersizdir; sessizce eski yaniti servis etmek yanlis olurdu.
    """

    __tablename__ = "ai_cache"
    __table_args__ = (UniqueConstraint("cache_key", name="uq_ai_cache_key"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    cache_key: Mapped[str] = mapped_column(String(96), index=True)
    dataset_id: Mapped[str] = mapped_column(String(32), index=True)
    kind: Mapped[str] = mapped_column(String(32))
    payload_json: Mapped[str] = mapped_column(Text)
    grounding_ratio: Mapped[float] = mapped_column(Float, default=0.0)
    cost_usd: Mapped[float] = mapped_column(Float, default=0.0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)
