"""In-memory and Redis response caches with privacy and false-hit guardrails."""
from __future__ import annotations

import hashlib
import math
import re
import time
from collections import Counter
from dataclasses import dataclass
from typing import Any, Callable


PRIVACY_PATTERNS = re.compile(
    r"\b(balance|password|credit[ ._-]?card|ssn|social[ ._-]?security|"
    r"user[ ._-]?\d+|account[ ._-]?\d+)\b",
    re.IGNORECASE,
)


def _is_uncacheable(query: str) -> bool:
    return bool(PRIVACY_PATTERNS.search(query))


def _looks_like_false_hit(query: str, cached_key: str) -> bool:
    """Reject semantically similar entries whose 4-digit facts differ."""
    nums_q = set(re.findall(r"\b\d{4}\b", query))
    nums_c = set(re.findall(r"\b\d{4}\b", cached_key))
    return bool(nums_q and nums_c and nums_q != nums_c)


@dataclass(slots=True)
class CacheEntry:
    key: str
    value: str
    created_at: float
    metadata: dict[str, str]


class ResponseCache:
    """TTL in-memory cache with lightweight semantic similarity guardrails."""

    def __init__(
        self,
        ttl_seconds: int = 3600,
        similarity_threshold: float = 0.75,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self.ttl_seconds = ttl_seconds
        self.similarity_threshold = similarity_threshold
        self._clock = clock
        self._entries: list[CacheEntry] = []
        self.false_hit_log: list[dict[str, object]] = []

    def get(self, query: str) -> tuple[str | None, float]:
        if _is_uncacheable(query):
            return None, 0.0

        now = self._clock()
        self._entries = [
            entry for entry in self._entries
            if now - entry.created_at <= self.ttl_seconds
        ]

        best_score = 0.0
        best_entry: CacheEntry | None = None
        for entry in self._entries:
            score = self.similarity(query, entry.key)
            if score > best_score:
                best_score = score
                best_entry = entry

        if best_entry is None or best_score < self.similarity_threshold:
            return None, best_score

        if _looks_like_false_hit(query, best_entry.key):
            self.false_hit_log.append(
                {
                    "query": query,
                    "cached_key": best_entry.key,
                    "score": best_score,
                    "reason": "date_or_number_mismatch",
                }
            )
            return None, best_score

        return best_entry.value, best_score

    def set(
        self,
        query: str,
        value: str,
        metadata: dict[str, str] | None = None,
    ) -> bool:
        if _is_uncacheable(query):
            return False
        self._entries.append(
            CacheEntry(
                key=query,
                value=value,
                created_at=self._clock(),
                metadata=metadata or {},
            )
        )
        return True

    @staticmethod
    def similarity(a: str, b: str) -> float:
        """Cosine similarity over normalized words plus character trigrams."""
        if a.strip().casefold() == b.strip().casefold():
            return 1.0

        def tokenize(text: str) -> list[str]:
            normalized = re.sub(r"[^\w\s]", " ", text.casefold(), flags=re.UNICODE)
            words = normalized.split()
            trigrams = [
                word[idx : idx + 3]
                for word in words
                for idx in range(max(0, len(word) - 2))
            ]
            return words + trigrams

        vec_a = Counter(tokenize(a))
        vec_b = Counter(tokenize(b))
        if not vec_a or not vec_b:
            return 0.0

        common = set(vec_a) & set(vec_b)
        dot = sum(vec_a[key] * vec_b[key] for key in common)
        mag_a = math.sqrt(sum(value * value for value in vec_a.values()))
        mag_b = math.sqrt(sum(value * value for value in vec_b.values()))
        return dot / (mag_a * mag_b) if mag_a and mag_b else 0.0


class SharedRedisCache:
    """Redis-backed cache shared by multiple gateway instances."""

    def __init__(
        self,
        redis_url: str = "redis://localhost:6379/0",
        ttl_seconds: int = 3600,
        similarity_threshold: float = 0.75,
        prefix: str = "rl:cache:",
    ) -> None:
        try:
            import redis as redis_lib
        except ImportError as exc:  # pragma: no cover - environment dependent
            raise RuntimeError("Install redis: python -m pip install redis") from exc
        self.ttl_seconds = ttl_seconds
        self.similarity_threshold = similarity_threshold
        self.prefix = prefix
        self.false_hit_log: list[dict[str, object]] = []
        self._redis: Any = redis_lib.Redis.from_url(redis_url, decode_responses=True)

    def ping(self) -> bool:
        try:
            return bool(self._redis.ping())
        except Exception:
            return False

    def get(self, query: str) -> tuple[str | None, float]:
        if _is_uncacheable(query):
            return None, 0.0

        exact_key = f"{self.prefix}{self._query_hash(query)}"
        exact = self._redis.hget(exact_key, "response")
        if exact is not None:
            return str(exact), 1.0

        best_score = 0.0
        best_response: str | None = None
        best_query: str | None = None
        for key in self._redis.scan_iter(f"{self.prefix}*"):
            cached_query = self._redis.hget(key, "query")
            if not cached_query:
                continue
            score = ResponseCache.similarity(query, str(cached_query))
            if score > best_score:
                best_score = score
                response = self._redis.hget(key, "response")
                best_response = str(response) if response is not None else None
                best_query = str(cached_query)

        if best_response is None or best_score < self.similarity_threshold:
            return None, best_score
        if _looks_like_false_hit(query, best_query or ""):
            self.false_hit_log.append(
                {
                    "query": query,
                    "cached_key": best_query,
                    "score": best_score,
                    "reason": "date_or_number_mismatch",
                }
            )
            return None, best_score
        return best_response, best_score

    def set(
        self,
        query: str,
        value: str,
        metadata: dict[str, str] | None = None,
    ) -> bool:
        if _is_uncacheable(query):
            return False
        key = f"{self.prefix}{self._query_hash(query)}"
        mapping: dict[str, str] = {"query": query, "response": value}
        for meta_key, meta_value in (metadata or {}).items():
            mapping[f"meta:{meta_key}"] = meta_value
        self._redis.hset(key, mapping=mapping)
        self._redis.expire(key, self.ttl_seconds)
        return True

    def flush(self) -> None:
        keys = list(self._redis.scan_iter(f"{self.prefix}*"))
        if keys:
            self._redis.delete(*keys)

    def close(self) -> None:
        self._redis.close()

    @staticmethod
    def _query_hash(query: str) -> str:
        return hashlib.sha256(query.casefold().strip().encode()).hexdigest()[:16]
