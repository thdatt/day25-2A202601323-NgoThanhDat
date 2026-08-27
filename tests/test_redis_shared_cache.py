"""Redis shared-cache tests using an in-process fake server (no docker needed)."""
import pytest

from cache import SharedRedisCache

fakeredis = pytest.importorskip("fakeredis")


@pytest.fixture
def server():
    return fakeredis.FakeServer()


def _cache(server, **kw):
    client = fakeredis.FakeStrictRedis(server=server, decode_responses=True)
    kw.setdefault("ttl_seconds", 60)
    kw.setdefault("similarity_threshold", 0.75)
    return SharedRedisCache(client=client, **kw)


def test_get_set_roundtrip(server):
    cache = _cache(server)
    assert cache.set("Thời hạn hoàn tiền là bao lâu?", "Hoàn tiền tối đa 30 ngày.") is True
    value, score = cache.get("Thời hạn hoàn tiền là bao lâu?")
    assert value == "Hoàn tiền tối đa 30 ngày."
    assert score == 1.0
    assert cache.ping() is True
    assert cache.degraded_to_memory is False


def test_state_is_shared_across_instances(server):
    writer = _cache(server)
    reader = _cache(server)  # a *different* client, same server = another gateway instance
    writer.set("Chính sách đổi trả hàng thế nào?", "Đổi trả trong 7 ngày nếu còn nguyên tem.")

    # exact query written by A is visible to B (proves shared state)
    value, score = reader.get("Chính sách đổi trả hàng thế nào?")
    assert value == "Đổi trả trong 7 ngày nếu còn nguyên tem."
    assert score == 1.0

    # a semantic variant also resolves against A's entry from B
    loose = _cache(server, similarity_threshold=0.5)
    v2, s2 = loose.get("Chính sách đổi trả hàng ra sao?")
    assert v2 == "Đổi trả trong 7 ngày nếu còn nguyên tem."
    assert s2 >= 0.5


def test_privacy_guardrail_still_applies(server):
    cache = _cache(server)
    assert cache.set("what is my account 1234 balance?", "secret") is False
    assert cache.get("what is my account 1234 balance?") == (None, 0.0)


def test_false_hit_guardrail_across_instances(server):
    writer = _cache(server, similarity_threshold=0.1)
    reader = _cache(server, similarity_threshold=0.1)
    writer.set("refund policy 2025", "old policy text")
    value, score = reader.get("refund policy 2026")
    assert value is None
    assert score > 0.1
    assert reader.false_hit_log[-1]["reason"] == "date_or_number_mismatch"


def test_falls_back_to_memory_when_redis_unavailable():
    class BrokenRedis:
        def __getattr__(self, _name):
            def _boom(*_a, **_k):
                raise ConnectionError("redis down")
            return _boom

    cache = SharedRedisCache(client=BrokenRedis(), memory_fallback=True)
    assert cache.set("Giờ mở cửa cuối tuần?", "9h - 21h mỗi ngày.") is True
    assert cache.degraded_to_memory is True
    value, _ = cache.get("Giờ mở cửa cuối tuần?")
    assert value == "9h - 21h mỗi ngày."
    # guardrail intact even while degraded
    assert cache.set("my password is hunter2", "x") is False
