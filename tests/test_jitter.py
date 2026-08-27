import pytest

from jitter import retry_with_exponential_backoff_and_jitter


def test_retries_then_succeeds_without_real_sleep():
    attempts = {"n": 0}
    sleeps = []

    def fn():
        attempts["n"] += 1
        if attempts["n"] < 3:
            raise ConnectionError("temp")
        return "ok"

    result = retry_with_exponential_backoff_and_jitter(
        fn,
        max_attempts=4,
        base_delay=1,
        max_delay=4,
        sleep_fn=sleeps.append,
        rng=lambda low, high: high / 2,
    )
    assert result == "ok"
    assert attempts["n"] == 3
    assert sleeps == [0.5, 1.0]


def test_does_not_retry_programming_error():
    calls = {"n": 0}

    def fn():
        calls["n"] += 1
        raise ValueError("bad input")

    with pytest.raises(ValueError):
        retry_with_exponential_backoff_and_jitter(fn, sleep_fn=lambda _: None)
    assert calls["n"] == 1
