"""Observability: collect per-request telemetry and emit a reproducible metrics.json.

Captured:
- latency P50 / P95 / P99 (ms)
- availability = successful responses / total requests (a fallback answer still
  counts as "available" - the user got a usable reply)
- correctness = answers that were not blocked by the quality guardrail
- circuit_open_count (state -> OPEN transitions)
- cache: lookups, hit_rate, tokens_saved, cost_saved_usd
- served_from breakdown (primary / cache / fallback tiers)
"""
from __future__ import annotations

import json
from collections import Counter
from pathlib import Path
from typing import Any

import numpy as np


class MetricsCollector:
    def __init__(self, name: str = "run") -> None:
        self.name = name
        self.latencies_ms: list[float] = []
        self.total = 0
        self.available = 0          # got a usable answer (primary, cache, or fallback)
        self.correct = 0           # answer not blocked by the quality guardrail
        self.circuit_open_count = 0
        self.served_from: Counter[str] = Counter()

    def record_request(
        self,
        *,
        latency_ms: float,
        available: bool,
        correct: bool,
        served_from: str,
    ) -> None:
        self.total += 1
        self.latencies_ms.append(float(latency_ms))
        self.available += int(available)
        self.correct += int(correct)
        self.served_from[served_from] += 1

    def record_circuit_open(self, n: int = 1) -> None:
        self.circuit_open_count += n

    @staticmethod
    def _pct(values: list[float], q: float) -> float:
        if not values:
            return 0.0
        return round(float(np.percentile(values, q)), 3)

    def snapshot(self, *, cache_stats: dict[str, Any] | None = None) -> dict[str, Any]:
        return {
            "scenario": self.name,
            "requests": self.total,
            "latency_ms": {
                "p50": self._pct(self.latencies_ms, 50),
                "p95": self._pct(self.latencies_ms, 95),
                "p99": self._pct(self.latencies_ms, 99),
                "max": round(max(self.latencies_ms), 3) if self.latencies_ms else 0.0,
            },
            "availability": round(self.available / self.total, 4) if self.total else 0.0,
            "correctness": round(self.correct / self.total, 4) if self.total else 0.0,
            "circuit_open_count": self.circuit_open_count,
            "served_from": dict(self.served_from),
            "cache": cache_stats or {},
        }


def dump_metrics(path: str | Path, payload: dict[str, Any]) -> Path:
    path = Path(path)
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    return path


if __name__ == "__main__":
    mc = MetricsCollector("demo")
    for i in range(20):
        mc.record_request(
            latency_ms=10 + i,
            available=True,
            correct=i % 5 != 0,
            served_from="primary" if i % 3 else "cache",
        )
    mc.record_circuit_open()
    print(json.dumps(mc.snapshot(), indent=2))
