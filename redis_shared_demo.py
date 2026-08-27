"""Prove the Redis cache is shared across gateway instances, and that it fails
over to in-memory when Redis is gone.

Uses a real Redis if $REDIS_URL points at one; otherwise an in-process fake
(fakeredis) so the demo always runs.
"""
from __future__ import annotations

import os
import sys

from cache import SharedRedisCache

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")  # Windows console safety


def _two_instances_same_backend():
    url = os.getenv("REDIS_URL")
    if url:
        a = SharedRedisCache(redis_url=url, prefix="demo:")
        b = SharedRedisCache(redis_url=url, prefix="demo:")
        if a.ping():
            a.flush()
            return a, b, f"real Redis at {url}"
    import fakeredis

    server = fakeredis.FakeServer()
    mk = lambda: SharedRedisCache(
        client=fakeredis.FakeStrictRedis(server=server, decode_responses=True), prefix="demo:"
    )
    return mk(), mk(), "in-process fakeredis (no external Redis)"


def main() -> None:
    inst_a, inst_b, backend = _two_instances_same_backend()
    print(f"backend: {backend}\n")

    q = "Chính sách bảo hành sản phẩm áp dụng trong bao lâu?"
    print(f"[instance A] set({q!r}, ...)")
    inst_a.set(q, "Bảo hành 12 tháng cho lỗi nhà sản xuất.")

    print(f"[instance B] get({q!r})   # different instance, same Redis")
    value, score = inst_b.get(q)
    print(f"   -> HIT  score={score:.3f}  value={value!r}")
    assert value is not None, "expected instance B to see instance A's write"

    variant = "Bảo hành sản phẩm trong bao lâu?"
    v2, s2 = inst_b.get(variant)
    print(f"[instance B] get({variant!r})  # semantic variant -> score={s2:.3f} "
          f"({'HIT' if v2 else 'below threshold, MISS'})")

    print("\n[instance B] set('what is my account 1234 balance?', ...)  # privacy guardrail")
    print(f"   -> cached? {inst_b.set('what is my account 1234 balance?', 'secret')}  (must be False)")

    print("\nNow simulate Redis going down for a third instance:")

    class BrokenRedis:
        def __getattr__(self, _n):
            def boom(*_a, **_k):
                raise ConnectionError("redis unreachable")
            return boom

    degraded = SharedRedisCache(client=BrokenRedis(), memory_fallback=True)
    degraded.set("Giờ mở cửa?", "8h - 22h hằng ngày.")
    v, _ = degraded.get("Giờ mở cửa?")
    print(f"   set/get still work; degraded_to_memory={degraded.degraded_to_memory}; value={v!r}")


if __name__ == "__main__":
    main()
