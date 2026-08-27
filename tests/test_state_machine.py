import pytest

from state_machine import CircuitBreaker, CircuitOpenError, CircuitState


def test_closed_opens_and_recovers():
    now = [0.0]
    breaker = CircuitBreaker(2, 5, 1, (ConnectionError,), clock=lambda: now[0])

    def fail():
        raise ConnectionError("down")

    for _ in range(2):
        with pytest.raises(ConnectionError):
            breaker.call(fail)
    assert breaker.state == CircuitState.OPEN

    with pytest.raises(CircuitOpenError):
        breaker.call(lambda: "should-not-run")

    now[0] = 5.1
    assert breaker.call(lambda: "ok") == "ok"
    assert breaker.state == CircuitState.CLOSED


def test_non_expected_exception_does_not_trip_breaker():
    breaker = CircuitBreaker(expected_exceptions=(ConnectionError,))
    with pytest.raises(ValueError):
        breaker.call(lambda: (_ for _ in ()).throw(ValueError("bad input")))
    assert breaker.failure_count == 0
