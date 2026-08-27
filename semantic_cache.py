"""Semantic cache using Gemini embeddings; supports injected embedders for tests."""
from __future__ import annotations

import os
import time
from dataclasses import dataclass
from typing import Callable

import numpy as np


@dataclass(slots=True)
class SemanticCacheEntry:
    query: str
    embedding: np.ndarray
    response: str
    created_at: float


class SemanticCache:
    def __init__(
        self,
        similarity_threshold: float = 0.88,
        ttl_seconds: float = 3600.0,
        embedder: Callable[[str], np.ndarray] | None = None,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self.threshold = similarity_threshold
        self.ttl_seconds = ttl_seconds
        self._clock = clock
        self.cache_store: list[SemanticCacheEntry] = []
        self.total_requests = 0
        self.hits = 0
        self.misses = 0
        self._embedder = embedder or self._build_gemini_embedder()

    @staticmethod
    def _normalize(vector: np.ndarray) -> np.ndarray:
        vector = np.asarray(vector, dtype=float)
        norm = np.linalg.norm(vector)
        return vector / norm if norm > 0 else vector

    def _build_gemini_embedder(self) -> Callable[[str], np.ndarray]:
        api_key = os.getenv("GOOGLE_API_KEY")
        if not api_key:
            raise RuntimeError(
                "GOOGLE_API_KEY is required for real semantic-cache embeddings. "
                "Use an injected embedder only for offline tests."
            )
        try:
            from google import genai
        except ImportError as exc:
            raise RuntimeError("Install google-genai") from exc
        client = genai.Client(api_key=api_key)

        def embed(text: str) -> np.ndarray:
            result = client.models.embed_content(model="gemini-embedding-2", contents=text)
            return self._normalize(np.array(result.embeddings[0].values, dtype=float))

        return embed

    def lookup(self, query: str) -> tuple[str | None, float]:
        self.total_requests += 1
        query_vec = self._normalize(self._embedder(query))
        now = self._clock()
        self.cache_store = [
            entry for entry in self.cache_store
            if now - entry.created_at < self.ttl_seconds
        ]
        if not self.cache_store:
            self.misses += 1
            return None, -1.0

        best = max(
            self.cache_store,
            key=lambda entry: float(np.dot(query_vec, entry.embedding)),
        )
        score = float(np.dot(query_vec, best.embedding))
        if score >= self.threshold:
            self.hits += 1
            return best.response, score
        self.misses += 1
        return None, score

    def store(self, query: str, response: str) -> None:
        vector = self._normalize(self._embedder(query))
        self.cache_store.append(
            SemanticCacheEntry(query, vector, response, self._clock())
        )

    def get_hit_rate(self) -> float:
        return self.hits / self.total_requests if self.total_requests else 0.0


if __name__ == "__main__":
    import sys

    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")  # Windows console safety

    cache = SemanticCache(similarity_threshold=0.85, ttl_seconds=600)
    first = "Làm thế nào để quên mật khẩu và lấy lại tài khoản?"
    second = "Quên password lấy lại tài khoản thế nào?"
    cache.store(first, "Vào Cài đặt -> Bảo mật -> Khôi phục tài khoản.")
    print(cache.lookup(second))
    print(f"hit_rate={cache.get_hit_rate():.2%}")
