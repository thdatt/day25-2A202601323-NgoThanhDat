"""Named-provider routing with budget-aware downgrade.

The circuit breaker decides *whether* a dependency is healthy; the router decides
*which named provider* a request should go to. Providers are ordered from most to
least capable. Once the month's spend crosses a soft limit the router downgrades
every request to the cheapest provider (a "budget circuit breaker").
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable


@dataclass(slots=True)
class Provider:
    name: str                      # e.g. "gpt-4o", "gemini-1.5-pro", "gpt-4o-mini"
    tier: str                      # "premium" | "standard" | "cheap"
    usd_per_1k_tokens: float       # blended input+output price
    call: Callable[[str], str] = field(repr=False, default=lambda p: f"[stub] {p}")


class ProviderRouter:
    def __init__(
        self,
        providers: list[Provider],
        *,
        monthly_budget_usd: float = 10.0,
        soft_limit_ratio: float = 0.80,
    ) -> None:
        if not providers:
            raise ValueError("at least one provider is required")
        # Most capable first, cheapest last.
        self.providers = list(providers)
        self.cheapest = min(providers, key=lambda p: p.usd_per_1k_tokens)
        self.monthly_budget_usd = monthly_budget_usd
        self.soft_limit_ratio = soft_limit_ratio
        self.spent_usd = 0.0
        self.route_log: list[dict[str, object]] = []

    @property
    def budget_used_ratio(self) -> float:
        return self.spent_usd / self.monthly_budget_usd if self.monthly_budget_usd else 1.0

    def over_soft_limit(self) -> bool:
        return self.budget_used_ratio >= self.soft_limit_ratio

    def route(self, query: str) -> Provider:
        """Return the provider this query should be sent to (by name)."""
        chosen = self.cheapest if self.over_soft_limit() else self.providers[0]
        self.route_log.append(
            {
                "query": query,
                "provider": chosen.name,
                "tier": chosen.tier,
                "budget_used_ratio": round(self.budget_used_ratio, 4),
                "downgraded": chosen is self.cheapest and chosen is not self.providers[0],
            }
        )
        return chosen

    def record_spend(self, tokens: int, provider: Provider) -> float:
        cost = tokens / 1000.0 * provider.usd_per_1k_tokens
        self.spent_usd += cost
        return cost


def default_router(monthly_budget_usd: float = 5.0) -> ProviderRouter:
    return ProviderRouter(
        [
            Provider("gpt-4o", "premium", 0.0075, lambda p: f"gpt-4o: {p}"),
            Provider("gemini-1.5-pro", "standard", 0.0035, lambda p: f"gemini-1.5-pro: {p}"),
            Provider("gpt-4o-mini", "cheap", 0.0005, lambda p: f"gpt-4o-mini: {p}"),
        ],
        monthly_budget_usd=monthly_budget_usd,
        soft_limit_ratio=0.80,
    )


if __name__ == "__main__":
    # Small budget so the 80% soft limit is crossed within the demo.
    router = default_router(monthly_budget_usd=0.10)
    print(f"budget=${router.monthly_budget_usd:.2f}, soft limit={router.soft_limit_ratio:.0%}")
    for i in range(1, 11):
        provider = router.route(f"request-{i}")
        router.record_spend(tokens=1600, provider=provider)
        tag = "  <-- downgraded (budget)" if router.route_log[-1]["downgraded"] else ""
        print(
            f"  req {i:>2}: -> {provider.name:<14} ({provider.tier:<8}) "
            f"spent=${router.spent_usd:.4f} used={router.budget_used_ratio:.0%}{tag}"
        )
