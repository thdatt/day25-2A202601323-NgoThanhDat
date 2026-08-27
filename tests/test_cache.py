from cache import ResponseCache, _is_uncacheable


def test_ttl_and_exact_hit():
    now = [0.0]
    cache = ResponseCache(ttl_seconds=10, similarity_threshold=0.7, clock=lambda: now[0])
    assert cache.set("refund policy", "30 days")
    assert cache.get("refund policy") == ("30 days", 1.0)
    now[0] = 11.0
    assert cache.get("refund policy")[0] is None


def test_privacy_query_not_cached():
    cache = ResponseCache()
    assert _is_uncacheable("what is my account 1234 balance?")
    assert cache.set("what is my account 1234 balance?", "secret") is False
    assert cache.get("what is my account 1234 balance?") == (None, 0.0)


def test_false_hit_number_guardrail():
    cache = ResponseCache(similarity_threshold=0.1)
    cache.set("refund policy 2025", "old")
    value, score = cache.get("refund policy 2026")
    assert value is None
    assert score > 0.1
    assert cache.false_hit_log[-1]["reason"] == "date_or_number_mismatch"
