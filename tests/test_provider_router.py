from provider_router import Provider, ProviderRouter, default_router


def _router(**kw):
    return ProviderRouter(
        [
            Provider("gpt-4o", "premium", 0.0075),
            Provider("gemini-1.5-pro", "standard", 0.0035),
            Provider("gpt-4o-mini", "cheap", 0.0005),
        ],
        monthly_budget_usd=1.0,
        **kw,
    )


def test_routes_to_premium_while_under_budget():
    router = _router(soft_limit_ratio=0.8)
    p = router.route("hello")
    assert p.name == "gpt-4o"
    assert router.route_log[-1]["provider"] == "gpt-4o"
    assert router.route_log[-1]["downgraded"] is False


def test_downgrades_to_cheapest_past_soft_limit():
    router = _router(soft_limit_ratio=0.8)
    router.spent_usd = 0.85  # 85% of a $1 budget spent
    assert router.over_soft_limit()
    p = router.route("hello")
    assert p.name == "gpt-4o-mini"
    assert p.tier == "cheap"
    assert router.route_log[-1]["downgraded"] is True


def test_record_spend_accumulates_cost():
    router = default_router()
    provider = router.route("q")
    cost = router.record_spend(tokens=2000, provider=provider)
    assert cost == round(2000 / 1000 * provider.usd_per_1k_tokens, 10)
    assert router.spent_usd == cost
