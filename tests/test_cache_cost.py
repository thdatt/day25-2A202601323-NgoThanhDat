from cache import ResponseCache


def test_hit_rate_and_cost_saved_accumulate():
    cache = ResponseCache(ttl_seconds=600, similarity_threshold=0.8, usd_per_1k_tokens=0.005)
    q = "Chính sách hoàn tiền của công ty áp dụng trong bao lâu?"
    cache.set(q, "Hoàn tiền tối đa 30 ngày kể từ ngày mua.")

    assert cache.get(q)[0] is not None          # hit
    assert cache.get(q)[0] is not None          # hit
    assert cache.get("Câu hỏi hoàn toàn khác về bảo hành sản phẩm")[0] is None  # miss

    stats = cache.stats()
    assert stats["hits"] == 2
    assert stats["misses"] == 1
    assert stats["hit_rate"] == round(2 / 3, 4)
    assert stats["tokens_saved"] > 0
    assert stats["cost_saved_usd"] > 0
    # cost = tokens_saved / 1000 * price
    assert abs(stats["cost_saved_usd"] - stats["tokens_saved"] / 1000 * 0.005) < 1e-9


def test_privacy_and_false_hit_do_not_count_as_hits():
    cache = ResponseCache(similarity_threshold=0.1)
    cache.set("refund policy 2025", "old")
    cache.get("refund policy 2026")                     # false-hit -> miss
    cache.get("what is my account 1234 balance?")       # uncacheable -> not counted
    assert cache.hits == 0
    assert cache.misses == 1
    assert cache.stats()["false_hits_blocked"] == 1
