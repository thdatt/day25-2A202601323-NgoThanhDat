"""Stretch goal: property-based fuzzing of the circuit-breaker state machine."""
import pytest

from state_machine import CircuitBreaker, CircuitOpenError, CircuitState

hyp = pytest.importorskip("hypothesis")
from hypothesis import given, settings  # noqa: E402
from hypothesis import strategies as st  # noqa: E402

VALID = {CircuitState.CLOSED, CircuitState.OPEN, CircuitState.HALF_OPEN}


@settings(max_examples=300, deadline=None)
@given(
    ops=st.lists(st.sampled_from(["ok", "fail", "wait"]), min_size=1, max_size=80),
    failure_threshold=st.integers(min_value=1, max_value=5),
    success_threshold=st.integers(min_value=1, max_value=3),
)
def test_invariants_hold_under_random_sequences(ops, failure_threshold, success_threshold):
    now = [0.0]
    world = {"up": True}
    breaker = CircuitBreaker(
        failure_threshold=failure_threshold,
        reset_timeout_seconds=2.0,
        success_threshold=success_threshold,
        expected_exceptions=(ConnectionError,),
        clock=lambda: now[0],
    )

    def provider():
        if not world["up"]:
            raise ConnectionError("down")
        return "ok"

    for op in ops:
        if op == "wait":
            now[0] += 1.0
            continue
        world["up"] = op == "ok"
        state_before = breaker.state
        ready = (now[0] - breaker.last_state_change) >= breaker.reset_timeout_seconds
        try:
            breaker.call(provider)
        except CircuitOpenError:
            # fail-fast may only happen from OPEN before the reset timeout
            assert state_before == CircuitState.OPEN and not ready
        except ConnectionError:
            pass

        assert breaker.state in VALID
        assert breaker.failure_count >= 0
        assert breaker.success_count >= 0

    # Structural invariants on the audit trail.
    for e in breaker.transition_log:
        assert e["from"] != e["to"]
        assert e["from"] in {s.value for s in VALID}
        assert e["to"] in {s.value for s in VALID}
    assert breaker.open_count == sum(1 for e in breaker.transition_log if e["to"] == "OPEN")
    # CLOSED is only ever re-entered via a successful HALF_OPEN probe.
    for e in breaker.transition_log:
        if e["to"] == "CLOSED":
            assert e["from"] == "HALF_OPEN"
