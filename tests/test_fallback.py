from fallback_ladder import FallbackLadderAgent


def test_falls_to_smaller_model():
    result = FallbackLadderAgent().execute("refund")
    assert result["status"] == "success"
    assert result["source"].startswith("Tier 3")


def test_static_fallback_when_everything_fails():
    def fail(_):
        raise TimeoutError("down")

    result = FallbackLadderAgent(primary=fail, backup=fail, smaller=fail, cache=lambda _: None).execute("x")
    assert result["status"] == "hard_degraded"
    assert result["source"].startswith("Tier 5")
