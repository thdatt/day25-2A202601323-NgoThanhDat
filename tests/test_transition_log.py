import pytest

from state_machine import CircuitBreaker, CircuitOpenError, CircuitState


def test_transition_log_records_full_recovery_cycle():
    now = [0.0]
    breaker = CircuitBreaker(2, 5, 1, (ConnectionError,), clock=lambda: now[0])

    def fail():
        raise ConnectionError("down")

    for _ in range(2):
        with pytest.raises(ConnectionError):
            breaker.call(fail)
    with pytest.raises(CircuitOpenError):
        breaker.call(lambda: "nope")
    now[0] = 5.1
    breaker.call(lambda: "ok")

    hops = [(e["from"], e["to"]) for e in breaker.transition_log]
    assert hops == [
        ("CLOSED", "OPEN"),
        ("OPEN", "HALF_OPEN"),
        ("HALF_OPEN", "CLOSED"),
    ]
    assert breaker.open_count == 1
    assert "threshold" in breaker.transition_log[0]["reason"]
    assert breaker.transition_log[0]["at"] == 0.0
    assert breaker.state == CircuitState.CLOSED


def test_open_count_increments_on_each_trip():
    now = [0.0]
    breaker = CircuitBreaker(1, 1, 1, (ConnectionError,), clock=lambda: now[0])

    def fail():
        raise ConnectionError("x")

    with pytest.raises(ConnectionError):
        breaker.call(fail)          # trip 1
    now[0] = 2.0
    with pytest.raises(ConnectionError):
        breaker.call(fail)          # probe fails -> trip 2
    assert breaker.open_count == 2
