"""AI cagri telemetrisi.

Bir orkestrasyon framework'unun (LangSmith vb.) verdigi gozlemlenebilirligin
bize gereken kismi: her cagrinin modeli, token kirilimi, onbellek isabeti,
suresi ve tahmini maliyeti. Framework bagimliligi olmadan ~40 satir.
"""

from __future__ import annotations

import logging
from dataclasses import asdict, dataclass, field

_log = logging.getLogger("app.ai")


@dataclass(frozen=True, slots=True)
class ModelPricing:
    """USD / 1M token. Onbellek yazma ~1.25x giris, okuma ~0.1x giris."""

    input: float
    output: float

    @property
    def cache_write(self) -> float:
        return self.input * 1.25

    @property
    def cache_read(self) -> float:
        return self.input * 0.10


# Sonnet 5 icin 31.08.2026'ya kadar gecerli tanitim fiyati kullaniliyor
# (liste fiyati 3.00 / 15.00).
PRICING: dict[str, ModelPricing] = {
    "claude-opus-5": ModelPricing(5.00, 25.00),
    "claude-sonnet-5": ModelPricing(2.00, 10.00),
    "claude-haiku-4-5": ModelPricing(1.00, 5.00),
}
DEFAULT_PRICING = ModelPricing(5.00, 25.00)


def pricing_for(model: str) -> ModelPricing:
    return PRICING.get(model, DEFAULT_PRICING)


@dataclass(slots=True)
class CallStats:
    label: str
    model: str
    input_tokens: int = 0
    output_tokens: int = 0
    cache_write_tokens: int = 0
    cache_read_tokens: int = 0
    duration_ms: int = 0
    attempts: int = 1

    @property
    def cost_usd(self) -> float:
        price = pricing_for(self.model)
        return (
            self.input_tokens * price.input
            + self.output_tokens * price.output
            + self.cache_write_tokens * price.cache_write
            + self.cache_read_tokens * price.cache_read
        ) / 1_000_000

    @property
    def cache_hit(self) -> bool:
        return self.cache_read_tokens > 0

    def log(self) -> None:
        _log.info(
            "ai_call",
            extra={
                **asdict(self),
                "cost_usd": round(self.cost_usd, 6),
                "cache_hit": self.cache_hit,
            },
        )


@dataclass(slots=True)
class RunStats:
    """Bir orkestrasyon kosusunun toplami."""

    calls: list[CallStats] = field(default_factory=list)

    def add(self, stats: CallStats) -> None:
        stats.log()
        self.calls.append(stats)

    @property
    def total_cost_usd(self) -> float:
        return sum(c.cost_usd for c in self.calls)

    @property
    def cache_read_tokens(self) -> int:
        return sum(c.cache_read_tokens for c in self.calls)

    def to_dict(self) -> dict[str, object]:
        return {
            "call_count": len(self.calls),
            "input_tokens": sum(c.input_tokens for c in self.calls),
            "output_tokens": sum(c.output_tokens for c in self.calls),
            "cache_write_tokens": sum(c.cache_write_tokens for c in self.calls),
            "cache_read_tokens": self.cache_read_tokens,
            "cache_hit_calls": sum(1 for c in self.calls if c.cache_hit),
            "total_cost_usd": round(self.total_cost_usd, 5),
            "duration_ms": sum(c.duration_ms for c in self.calls),
        }
