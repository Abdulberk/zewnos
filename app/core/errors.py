"""Uygulama hata sozlesmesi.

Tasarim karari: her hata bir `code` tasir. Istemci (Next.js) mesaj metnine
degil bu koda gore dallanir -- mesaj metni degisse bile istemci kirilmaz.

Bu modul bilerek saf Python'dur: `domain` katmani da bu hatalari
firlatabilsin diye FastAPI'ye bagimli degildir. HTTP'ye cevirme isi
`app/api/errors.py` icindeki tek bir handler'da yapilir.
"""

from __future__ import annotations

from typing import Any


class AppError(Exception):
    """Tum uygulama hatalarinin tabani."""

    code: str = "internal_error"
    http_status: int = 500
    message: str = "Beklenmeyen bir hata oluştu."

    def __init__(
        self,
        message: str | None = None,
        *,
        details: dict[str, Any] | None = None,
    ) -> None:
        self.message = message or self.__class__.message
        self.details = details or {}
        super().__init__(self.message)

    def to_dict(self) -> dict[str, Any]:
        return {"code": self.code, "message": self.message, "details": self.details}


# --------------------------------------------------------------------------
# 4xx -- istemci kaynakli
# --------------------------------------------------------------------------
class NotFoundError(AppError):
    code = "not_found"
    http_status = 404
    message = "Kayıt bulunamadı."


class InvalidRequestError(AppError):
    code = "invalid_request"
    http_status = 400
    message = "İstek geçersiz."


class FileTooLargeError(AppError):
    code = "file_too_large"
    http_status = 413
    message = "Dosya boyutu izin verilen sınırı aşıyor."


class UnknownPackError(AppError):
    code = "unknown_pack"
    http_status = 400
    message = "Bilinmeyen veri seti tipi (pack)."


# --------------------------------------------------------------------------
# Ingestion -- CSV okuma / dogrulama
# --------------------------------------------------------------------------
class IngestionError(AppError):
    code = "ingestion_failed"
    http_status = 422
    message = "CSV dosyası işlenemedi."


class EmptyDatasetError(IngestionError):
    code = "empty_dataset"
    message = "Dosyada işlenebilir veri satırı yok."


class SchemaMismatchError(IngestionError):
    code = "schema_mismatch"
    message = "CSV kolonları beklenen şema ile uyuşmuyor."


class UndecodableFileError(IngestionError):
    code = "undecodable_file"
    message = "Dosya bilinen hiçbir karakter kodlamasıyla okunamadı."


# --------------------------------------------------------------------------
# AI katmani
# --------------------------------------------------------------------------
class AIError(AppError):
    code = "ai_error"
    http_status = 502
    message = "AI servisinden yanıt alınamadı."


class AINotConfiguredError(AIError):
    code = "ai_not_configured"
    http_status = 503
    message = (
        "ANTHROPIC_API_KEY tanımlı değil. .env dosyasını oluşturup anahtarı "
        "ekledikten sonra tekrar deneyin."
    )


class AIRateLimitedError(AIError):
    code = "ai_rate_limited"
    http_status = 429
    message = "AI servisi istek limitini aştı, lütfen biraz sonra tekrar deneyin."


class AIResponseInvalidError(AIError):
    code = "ai_response_invalid"
    message = "AI yanıtı beklenen şemaya uymadı."


class AIRefusedError(AIError):
    code = "ai_refused"
    message = "AI bu isteği güvenlik gerekçesiyle yanıtlamadı."
