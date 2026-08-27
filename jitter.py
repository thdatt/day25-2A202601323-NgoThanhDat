"""Retry helpers using exponential backoff with Full Jitter."""
from __future__ import annotations

import random
import time
from typing import Any, Callable, Tuple, Type


def retry_with_exponential_backoff_and_jitter(
    func: Callable[[], Any],
    max_attempts: int = 5,
    base_delay: float = 1.0,
    max_delay: float = 32.0,
    retryable_exceptions: Tuple[Type[Exception], ...] = (ConnectionError, TimeoutError),
    sleep_fn: Callable[[float], None] = time.sleep,
    rng: Callable[[float, float], float] = random.uniform,
) -> Any:
    if max_attempts < 1:
        raise ValueError("max_attempts must be >= 1")

    for attempt in range(max_attempts):
        try:
            return func()
        except retryable_exceptions:
            if attempt == max_attempts - 1:
                raise
            backoff = min(max_delay, base_delay * (2**attempt))
            sleep_fn(rng(0.0, backoff))

    raise RuntimeError("unreachable")


if __name__ == "__main__":
    import sys

    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")  # Windows console safety

    calls = {"count": 0}

    def recover() -> str:
        calls["count"] += 1
        if calls["count"] <= 2:
            raise ConnectionError("temporary failure")
        return "service recovered"

    print(retry_with_exponential_backoff_and_jitter(recover, base_delay=0.2))
