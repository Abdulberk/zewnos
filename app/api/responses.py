"""Uclarin OpenAPI'de ilan ettigi hata yanitlari.

Neden ayri bir modul: hata govdesi (`ErrorResponse`) tum uclarda ayni ama
FastAPI bunu kendiliginden semaya yazmaz -- yazilmazsa `openapi-typescript`
ile uretilen istemci tipleri hata dalini hic gormez ve frontend `error.code`
uzerinden dallanamaz. Sozlesmenin tek kaynaktan uretilmesi iddiasi ancak
hata yollari da ilan edilirse dogru olur.

Kumeler uca gore ayrilir: yalnizca yukleme ucu 413 dondurebilir, yalnizca
AI uclari 429/502/503 dondurebilir. "Her uca her hatayi" yazmak sozlesmeyi
dogru degil, sadece kalabalik yapardi.
"""

from __future__ import annotations

from typing import Any

from app.schemas.common import ErrorResponse

_Responses = dict[int | str, dict[str, Any]]


def _model(description: str) -> dict[str, Any]:
    return {"model": ErrorResponse, "description": description}


COMMON_ERRORS: _Responses = {
    400: _model("İstek geçersiz (bilinmeyen rapor tipi, hatalı parametre)"),
    404: _model("Kayıt bulunamadı"),
    422: _model("Dosya işlenemedi ya da doğrulama hatası"),
    500: _model("Beklenmeyen hata"),
}

UPLOAD_ERRORS: _Responses = {
    **COMMON_ERRORS,
    413: _model("Dosya boyutu izin verilen sınırı aşıyor"),
}

AI_ERRORS: _Responses = {
    **COMMON_ERRORS,
    429: _model("AI servisi istek limitini aştı"),
    502: _model("AI servisinden geçerli yanıt alınamadı"),
    503: _model("AI yapılandırılmamış (ANTHROPIC_API_KEY yok)"),
}
