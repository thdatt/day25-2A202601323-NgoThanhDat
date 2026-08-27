import numpy as np

from semantic_cache import SemanticCache


def fake_embed(text: str) -> np.ndarray:
    if "password" in text.casefold() or "mật khẩu" in text.casefold():
        return np.array([1.0, 0.0])
    return np.array([0.0, 1.0])


def test_semantic_hit_and_miss_without_api():
    cache = SemanticCache(0.8, 100, embedder=fake_embed)
    cache.store("quên mật khẩu", "reset instructions")
    assert cache.lookup("password forgotten")[0] == "reset instructions"
    assert cache.lookup("delete account")[0] is None
    assert cache.total_requests == 2
    assert cache.hits == 1
    assert cache.misses == 1
