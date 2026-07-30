"""Hatalarin HTTP'ye cevrilmesi.

Tek yerde: domain ve servis katmanlari `AppError` firlatir, burasi onu
sozlesmeye uygun bir JSON govdesine cevirir. Boylece is mantigi HTTP'yi
bilmez ve istemci her hatada ayni sekli gorur.
"""

from __future__ import annotations

import logging

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from app.core.errors import AppError

_log = logging.getLogger(__name__)


def register_exception_handlers(app: FastAPI) -> None:
    @app.exception_handler(AppError)
    async def _app_error(_: Request, exc: AppError) -> JSONResponse:
        # Beklenen hatalar: sessizce log, istemciye anlamli mesaj.
        _log.info("app_error", extra={"code": exc.code, "detail": exc.details})
        return JSONResponse(status_code=exc.http_status, content=exc.to_dict())

    @app.exception_handler(RequestValidationError)
    async def _validation_error(_: Request, exc: RequestValidationError) -> JSONResponse:
        return JSONResponse(
            status_code=422,
            content={
                "code": "validation_error",
                "message": "İstek gövdesi ya da parametreleri geçersiz.",
                "details": {"errors": exc.errors()},
            },
        )

    @app.exception_handler(Exception)
    async def _unhandled(_: Request, exc: Exception) -> JSONResponse:
        # Beklenmeyen hata: tam iz logda, istemciye ic detay sizdirilmaz.
        _log.exception("unhandled_error", extra={"error_type": type(exc).__name__})
        return JSONResponse(
            status_code=500,
            content={
                "code": "internal_error",
                "message": "Beklenmeyen bir hata oluştu. Kayıtlar incelenmeli.",
                "details": {},
            },
        )
