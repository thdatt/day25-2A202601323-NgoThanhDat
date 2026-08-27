"""Integrated reference flow: cache -> breaker -> retry -> guardrail -> fallback."""
from __future__ import annotations

from typing import Callable

from cache import ResponseCache
from fallback_ladder import FallbackLadderAgent
from jitter import retry_with_exponential_backoff_and_jitter
from quanlity_guardrail import ProductionAgentGateway
from state_machine import CircuitBreaker, CircuitOpenError


class ReliableLLMGateway:
    def __init__(
        self,
        provider: Callable[[str], str],
        *,
        cache: ResponseCache | None = None,
        breaker: CircuitBreaker | None = None,
        quality_guard: ProductionAgentGateway | None = None,
        fallback: FallbackLadderAgent | None = None,
    ) -> None:
        self.provider = provider
        self.cache = cache or ResponseCache(ttl_seconds=600, similarity_threshold=0.80)
        self.breaker = breaker or CircuitBreaker(
            failure_threshold=3,
            reset_timeout_seconds=10,
            expected_exceptions=(ConnectionError, TimeoutError),
        )
        self.quality_guard = quality_guard or ProductionAgentGateway()
        self.fallback = fallback or FallbackLadderAgent()

    def handle(self, query: str, context: str) -> dict:
        cached, similarity = self.cache.get(query)
        if cached is not None:
            return {"status": "cache_hit", "source": "cache", "output": cached, "similarity": similarity}

        def call_provider() -> str:
            return self.breaker.call(self.provider, query)

        try:
            response = retry_with_exponential_backoff_and_jitter(
                call_provider,
                max_attempts=2,
                base_delay=0.05,
                max_delay=0.1,
            )
        except (ConnectionError, TimeoutError, CircuitOpenError) as exc:
            result = self.fallback.execute(query)
            # The fallback ladder always returns *something*, so its own "status"
            # field ("success" for a lower tier, "hard_degraded" for the static
            # tier) must not be forwarded as-is: from the gateway's point of view
            # the primary path failed and the answer is degraded.
            return {
                "status": "degraded_provider_fallback",
                "source": result["source"],
                "output": result["data"]["reply"],
                "detail": f"{type(exc).__name__}: {exc}",
                "fallback_status": result["status"],
            }

        guarded = self.quality_guard.evaluate(response, context, query)
        if guarded["status"] != "success":
            result = self.fallback.execute(query)
            return {
                "status": "degraded_quality_fallback",
                "source": result["source"],
                "output": result["data"]["reply"],
                "quality": guarded["metrics"],
                "fallback_status": result["status"],
            }

        self.cache.set(query, response)
        return {"status": "success", "source": "primary", "output": response, "quality": guarded["metrics"]}


def demo() -> None:
    """Deterministic walk-through of every branch of the integrated flow."""
    import sys

    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")  # Windows console safety

    context = "Chính sách công ty: thời hạn hoàn tiền tối đa là 30 ngày."
    query = "Thời hạn hoàn tiền là bao lâu?"

    print("1) Healthy provider + good answer -> cached for next time")
    healthy = ReliableLLMGateway(lambda _: "Theo chính sách, bạn được hoàn tiền trong 30 ngày.")
    print("  ", healthy.handle(query, context)["status"])
    print("   repeat same query ->", healthy.handle(query, context)["status"])

    print("2) Provider returns HTTP 200 but contradicts context (silent degradation)")
    degraded = ReliableLLMGateway(lambda _: "Chính sách hoàn tiền của công ty là 90 ngày.")
    out = degraded.handle(query, context)
    print("  ", out["status"], "->", out["output"])

    print("3) Provider down -> retry + circuit breaker exhausted -> fallback ladder")
    def down(_: str) -> str:
        raise ConnectionError("503 Service Unavailable")

    out = ReliableLLMGateway(down).handle(query, context)
    print("  ", out["status"], "via", out["source"], "->", out["output"])


if __name__ == "__main__":
    demo()
