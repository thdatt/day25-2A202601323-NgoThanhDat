"""Circuit breaker state machine for LLM/downstream calls."""
from __future__ import annotations

import time
from enum import Enum
from typing import Any, Callable, Tuple, Type


class CircuitState(str, Enum):
    CLOSED = "CLOSED"
    OPEN = "OPEN"
    HALF_OPEN = "HALF_OPEN"


class CircuitOpenError(RuntimeError):
    """Raised when the circuit is OPEN and calls must fail fast."""


class CircuitBreaker:
    """Three-state circuit breaker with automatic recovery probing."""

    def __init__(
        self,
        failure_threshold: int = 3,
        reset_timeout_seconds: float = 5.0,
        success_threshold: int = 1,
        expected_exceptions: Tuple[Type[Exception], ...] = (Exception,),
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        if failure_threshold < 1:
            raise ValueError("failure_threshold must be >= 1")
        if success_threshold < 1:
            raise ValueError("success_threshold must be >= 1")
        if reset_timeout_seconds < 0:
            raise ValueError("reset_timeout_seconds must be >= 0")

        self.failure_threshold = failure_threshold
        self.reset_timeout_seconds = reset_timeout_seconds
        self.success_threshold = success_threshold
        self.expected_exceptions = expected_exceptions
        self._clock = clock

        self.state = CircuitState.CLOSED
        self.failure_count = 0
        self.success_count = 0
        self.last_state_change = self._clock()

    def _transition(self, state: CircuitState) -> None:
        self.state = state
        self.last_state_change = self._clock()

    def _ready_to_probe(self) -> bool:
        return (self._clock() - self.last_state_change) >= self.reset_timeout_seconds

    def record_success(self) -> None:
        if self.state == CircuitState.HALF_OPEN:
            self.success_count += 1
            if self.success_count >= self.success_threshold:
                self.failure_count = 0
                self.success_count = 0
                self._transition(CircuitState.CLOSED)
        elif self.state == CircuitState.CLOSED:
            self.failure_count = 0

    def record_failure(self) -> None:
        self.failure_count += 1
        if self.state == CircuitState.HALF_OPEN:
            self.success_count = 0
            self._transition(CircuitState.OPEN)
        elif self.state == CircuitState.CLOSED and self.failure_count >= self.failure_threshold:
            self._transition(CircuitState.OPEN)

    def call(self, fn: Callable[..., Any], *args: Any, **kwargs: Any) -> Any:
        if self.state == CircuitState.OPEN:
            if not self._ready_to_probe():
                raise CircuitOpenError("Circuit is OPEN - fail fast")
            self.success_count = 0
            self._transition(CircuitState.HALF_OPEN)

        try:
            result = fn(*args, **kwargs)
        except self.expected_exceptions:
            self.record_failure()
            raise
        else:
            self.record_success()
            return result


def demo() -> None:
    """Small deterministic demo of CLOSED -> OPEN -> HALF_OPEN -> CLOSED."""
    import sys

    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")  # Windows console safety

    now = [0.0]
    down = [True]
    breaker = CircuitBreaker(
        failure_threshold=2,
        reset_timeout_seconds=2.0,
        success_threshold=1,
        expected_exceptions=(ConnectionError,),
        clock=lambda: now[0],
    )

    def provider(prompt: str) -> str:
        if down[0]:
            raise ConnectionError("503 Service Unavailable")
        return f"LLM Response: {prompt}"

    for idx in range(2):
        try:
            breaker.call(provider, f"request-{idx + 1}")
        except ConnectionError as exc:
            print(f"failure {idx + 1}: {exc}; state={breaker.state}")

    try:
        breaker.call(provider, "fail-fast")
    except CircuitOpenError as exc:
        print(f"fast-fail: {exc}; state={breaker.state}")

    now[0] += 2.1
    down[0] = False
    print(breaker.call(provider, "recovery probe"))
    print(f"recovered state={breaker.state}")


if __name__ == "__main__":
    demo()
