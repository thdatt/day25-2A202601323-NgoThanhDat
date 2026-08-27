from cache import ResponseCache
from fallback_ladder import FallbackLadderAgent
from reliability_gateway import ReliableLLMGateway
from state_machine import CircuitBreaker


def test_quality_degradation_triggers_fallback():
    def provider(_):
        return "Chính sách hoàn tiền là 90 ngày."

    fallback = FallbackLadderAgent(
        primary=lambda _: {"intent": "refund", "confidence": 0.9, "reply": "Fallback an toàn: 30 ngày."},
    )
    gateway = ReliableLLMGateway(provider, fallback=fallback)
    result = gateway.handle(
        "Thời hạn hoàn tiền là bao lâu?",
        "Chính sách: hoàn tiền tối đa 30 ngày.",
    )
    assert result["status"] == "degraded_quality_fallback"
    assert "30 ngày" in result["output"]


def test_provider_outage_returns_degraded_status_not_success():
    """A dead provider must not surface as top-level status 'success'."""

    def provider(_):
        raise ConnectionError("503 Service Unavailable")

    gateway = ReliableLLMGateway(
        provider,
        breaker=CircuitBreaker(failure_threshold=2, reset_timeout_seconds=1,
                               expected_exceptions=(ConnectionError, TimeoutError)),
    )
    result = gateway.handle("câu hỏi bất kỳ", "context bất kỳ")
    assert result["status"] == "degraded_provider_fallback"
    assert result["output"]


def test_cache_hit_short_circuits_provider():
    calls = {"n": 0}

    def provider(_):
        calls["n"] += 1
        return "Bạn được hoàn tiền trong 30 ngày theo chính sách."

    gateway = ReliableLLMGateway(provider, cache=ResponseCache(ttl_seconds=600, similarity_threshold=0.8))
    q, ctx = "Hoàn tiền trong bao lâu?", "Chính sách: hoàn tiền tối đa 30 ngày."
    first = gateway.handle(q, ctx)
    second = gateway.handle(q, ctx)
    assert first["status"] == "success"
    assert second["status"] == "cache_hit"
    assert calls["n"] == 1
