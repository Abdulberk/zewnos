"""Yapilandirilmis loglama.

Her kayit JSON satiri olarak cikar; uretimde dogrudan bir log toplayiciya
(Loki, CloudWatch, Datadog) beslenebilir. Her istek bir `request_id` alir ve
o istek boyunca uretilen tum kayitlar -- AI cagrisinin token/maliyet kaydi
dahil -- ayni id ile iliskilendirilir.
"""

from __future__ import annotations

import json
import logging
import sys
import uuid
from contextvars import ContextVar
from typing import Any

_request_id: ContextVar[str] = ContextVar("request_id", default="-")


def new_request_id() -> str:
    return uuid.uuid4().hex[:12]


def set_request_id(value: str) -> None:
    _request_id.set(value)


def get_request_id() -> str:
    return _request_id.get()


_RESERVED = frozenset(
    """
    name msg args levelname levelno pathname filename module exc_info exc_text
    stack_info lineno funcName created msecs relativeCreated thread threadName
    processName process taskName
    """.split()
)


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "ts": self.formatTime(record, "%Y-%m-%dT%H:%M:%S"),
            "level": record.levelname,
            "logger": record.name,
            "request_id": get_request_id(),
            "message": record.getMessage(),
        }
        # logger.info("...", extra={"tokens": 123}) ile gelen alanlari tasi
        for key, value in record.__dict__.items():
            if key not in _RESERVED and not key.startswith("_") and key not in payload:
                payload[key] = value
        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)
        return json.dumps(payload, ensure_ascii=False, default=str)


def configure_logging(level: str = "INFO") -> None:
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(JsonFormatter())

    root = logging.getLogger()
    root.handlers.clear()
    root.addHandler(handler)
    root.setLevel(level)

    # uvicorn'un kendi formatlayicilarini susturup tek formata indir
    for noisy in ("uvicorn", "uvicorn.error", "uvicorn.access"):
        logger = logging.getLogger(noisy)
        logger.handlers.clear()
        logger.propagate = True
