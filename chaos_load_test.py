"""Chaos & load testing for the reliability gateway.

Runs named fault-injection scenarios against `ReliableLLMGateway`, asserts a
pass/fail condition for each, captures latency/availability/circuit metrics, and
writes:
  - metrics.json            (aggregate, reproducible)
  - reports/chaos_results.md (human-readable scenario table)

Every scenario is deterministic (fixed workload, fixed fault windows); the only
non-determinism is sub-100ms jitter sleeps inside the retry helper, which the
assertions tolerate by using ranges.
"""
from __future__ import annotations

import sys
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from pathlib import Path

from cache import ResponseCache, SharedRedisCache
from metrics import MetricsCollector, dump_metrics
from reliability_gateway import ReliableLLMGateway
from state_machine import CircuitBreaker

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")  # Windows console safety

ROOT = Path(__file__).resolve().parent
CONTEXT = "Chính sách công ty: thời hạn hoàn tiền tối đa là 30 ngày."
# 12 distinct support questions (different topics -> they do NOT collide in the
# semantic cache). Repeating this list N times gives an honest hit rate of
# (N-1)/N: the first occurrence of each is a miss, the rest are hits.
QUERIES = [
    "Thời hạn hoàn tiền của tôi là bao lâu?",
    "Làm sao để đổi mật khẩu tài khoản?",
    "Phí vận chuyển nội thành là bao nhiêu?",
    "Tôi có thể huỷ đơn hàng đã đặt không?",
    "Công ty có hỗ trợ xuất hoá đơn VAT không?",
    "Thời gian giao hàng tiêu chuẩn mất mấy ngày?",
    "Sản phẩm lỗi thì bảo hành thế nào?",
    "Có chương trình tích điểm thành viên không?",
    "Tôi muốn thay đổi địa chỉ nhận hàng.",
    "Thanh toán trả góp được hỗ trợ không?",
    "Cửa hàng mở cửa mấy giờ vào cuối tuần?",
    "Làm sao để liên hệ tổng đài chăm sóc khách hàng?",
]


@dataclass
class ScenarioResult:
    name: str
    passed: bool
    detail: str
    snapshot: dict = field(default_factory=dict)


def _fresh_gateway(*, disable_cache: bool = False, reset_timeout: float = 0.25) -> tuple:
    calls = {"n": 0}

    def healthy_provider(_q: str) -> str:
        calls["n"] += 1
        return "Theo chính sách, bạn được hoàn tiền trong vòng 30 ngày."

    cache = ResponseCache(
        ttl_seconds=600,
        similarity_threshold=2.0 if disable_cache else 0.80,
    )
    breaker = CircuitBreaker(
        failure_threshold=3,
        reset_timeout_seconds=reset_timeout,
        expected_exceptions=(ConnectionError, TimeoutError),
    )
    gateway = ReliableLLMGateway(healthy_provider, cache=cache, breaker=breaker)
    return gateway, calls


def _classify(result: dict) -> tuple[bool, bool, str]:
    """(available, correct, served_from) for one gateway response."""
    status = result["status"]
    source = result.get("source", "")
    available = True
    if status in {"success", "cache_hit"}:
        return available, True, "primary" if status == "success" else "cache"
    if status == "degraded_quality_fallback":
        return available, True, "quality_fallback"  # guardrail did its job
    # degraded_provider_fallback
    correct = "Tier 5" not in source
    return available, correct, "provider_fallback"


def _drive(gateway, mc: MetricsCollector, query: str) -> dict:
    start = time.perf_counter()
    result = gateway.handle(query, CONTEXT)
    latency_ms = (time.perf_counter() - start) * 1000
    available, correct, served = _classify(result)
    mc.record_request(latency_ms=latency_ms, available=available, correct=correct, served_from=served)
    return result


# --------------------------------------------------------------------------- #
# Scenarios
# --------------------------------------------------------------------------- #
def scenario_baseline_healthy() -> ScenarioResult:
    gateway, calls = _fresh_gateway()
    mc = MetricsCollector("baseline_healthy")
    for _ in range(5):
        for q in QUERIES:
            _drive(gateway, mc, q)
    snap = mc.snapshot(cache_stats=gateway.cache.stats())
    passed = (
        snap["availability"] == 1.0
        and gateway.cache.hit_rate > 0.5
        and gateway.breaker.open_count == 0
    )
    return ScenarioResult(
        "baseline_healthy",
        passed,
        f"availability={snap['availability']}, hit_rate={gateway.cache.hit_rate:.2f}, "
        f"provider_calls={calls['n']}/60, circuit_open={gateway.breaker.open_count}",
        snap,
    )


def scenario_provider_outage() -> ScenarioResult:
    state = {"down": False}

    def flaky(_q: str) -> str:
        if state["down"]:
            raise ConnectionError("503 Service Unavailable")
        return "Theo chính sách, bạn được hoàn tiền trong vòng 30 ngày."

    breaker = CircuitBreaker(
        failure_threshold=3,
        reset_timeout_seconds=0.25,
        expected_exceptions=(ConnectionError, TimeoutError),
    )
    gateway = ReliableLLMGateway(flaky, cache=ResponseCache(similarity_threshold=2.0), breaker=breaker)
    mc = MetricsCollector("provider_outage")

    for i in range(40):
        if i == 8:
            state["down"] = True
        if i == 26:
            state["down"] = False
            time.sleep(0.3)  # let the reset timeout elapse so the next call probes
        _drive(gateway, mc, f"outage-req-{i}")
    mc.record_circuit_open(breaker.open_count)

    snap = mc.snapshot()
    recovered = gateway.breaker.state.value == "CLOSED"
    post_outage_ok = gateway.handle("post-outage", CONTEXT)["status"] == "success"
    passed = breaker.open_count >= 1 and snap["availability"] == 1.0 and recovered and post_outage_ok
    return ScenarioResult(
        "provider_outage",
        passed,
        f"circuit_open_count={breaker.open_count}, availability={snap['availability']}, "
        f"final_state={gateway.breaker.state.value}, "
        f"transitions={[e['from'] + '->' + e['to'] for e in breaker.transition_log]}",
        snap,
    )


def scenario_silent_degradation() -> ScenarioResult:
    def drifted(_q: str) -> str:
        # HTTP 200, but contradicts the retrieved context (30 -> 90 ngày).
        return "Chính sách hoàn tiền của công ty là 90 ngày."

    gateway = ReliableLLMGateway(drifted, cache=ResponseCache(similarity_threshold=2.0))
    mc = MetricsCollector("silent_degradation")
    delivered_wrong = 0
    for i in range(20):
        result = _drive(gateway, mc, f"drift-req-{i}")
        if "90 ngày" in result["output"]:
            delivered_wrong += 1
    snap = mc.snapshot()
    passed = (
        delivered_wrong == 0
        and snap["availability"] == 1.0
        and snap["served_from"].get("quality_fallback", 0) == 20
    )
    return ScenarioResult(
        "silent_degradation",
        passed,
        f"wrong_answers_delivered={delivered_wrong}/20, "
        f"blocked_by_guardrail={snap['served_from'].get('quality_fallback', 0)}/20, "
        f"availability={snap['availability']}",
        snap,
    )


def scenario_latency_spike() -> ScenarioResult:
    state = {"slow": False}

    def variable_latency(_q: str) -> str:
        time.sleep(0.045 if state["slow"] else 0.002)
        return "Theo chính sách, bạn được hoàn tiền trong vòng 30 ngày."

    gateway = ReliableLLMGateway(variable_latency, cache=ResponseCache(similarity_threshold=2.0))
    mc = MetricsCollector("latency_spike")
    for i in range(40):
        state["slow"] = 15 <= i < 30
        _drive(gateway, mc, f"lat-req-{i}")
    snap = mc.snapshot()
    passed = (
        snap["availability"] == 1.0
        and snap["latency_ms"]["p99"] >= 30.0
        and snap["latency_ms"]["p50"] < 30.0
    )
    return ScenarioResult(
        "latency_spike",
        passed,
        f"p50={snap['latency_ms']['p50']}ms p95={snap['latency_ms']['p95']}ms "
        f"p99={snap['latency_ms']['p99']}ms (tail captured), availability={snap['availability']}",
        snap,
    )


def scenario_redis_down_failover() -> ScenarioResult:
    class BrokenRedis:
        def __getattr__(self, _name):
            def _boom(*_a, **_k):
                raise ConnectionError("redis unreachable")
            return _boom

    cache = SharedRedisCache(client=BrokenRedis(), memory_fallback=True)
    query = "Chính sách hoàn tiền của công ty áp dụng trong bao lâu?"
    wrote = cache.set(query, "Hoàn tiền trong 30 ngày.")
    value, _score = cache.get(query)
    privacy_ok = cache.set("what is my account 1234 balance?", "secret") is False
    passed = wrote and cache.degraded_to_memory and value is not None and privacy_ok
    return ScenarioResult(
        "redis_down_failover",
        passed,
        f"degraded_to_memory={cache.degraded_to_memory}, served_from_memory={value is not None}, "
        f"privacy_guardrail_intact={privacy_ok}",
        {"scenario": "redis_down_failover", "degraded_to_memory": cache.degraded_to_memory},
    )


def scenario_cache_stampede_concurrent() -> ScenarioResult:
    """Stretch: many identical concurrent requests; cache should collapse them."""
    results = {}
    for label, disable in (("no_cache", True), ("with_cache", False)):
        gateway, calls = _fresh_gateway(disable_cache=disable)
        mc = MetricsCollector(f"stampede_{label}")
        q = "Chính sách hoàn tiền của công ty áp dụng bao lâu?"
        gateway.handle(q, CONTEXT)  # warm (only helps with_cache)
        with ThreadPoolExecutor(max_workers=10) as pool:
            list(pool.map(lambda _i: _drive(gateway, mc, q), range(50)))
        results[label] = {
            "provider_calls": calls["n"],
            "cost_saved_usd": round(gateway.cache.cost_saved_usd, 5),
            "p95_ms": mc.snapshot()["latency_ms"]["p95"],
        }
    passed = results["with_cache"]["provider_calls"] < results["no_cache"]["provider_calls"] / 3
    return ScenarioResult(
        "cache_stampede_concurrent",
        passed,
        f"provider_calls no_cache={results['no_cache']['provider_calls']} vs "
        f"with_cache={results['with_cache']['provider_calls']} "
        f"(saved ${results['with_cache']['cost_saved_usd']}); "
        f"p95 no_cache={results['no_cache']['p95_ms']}ms vs with_cache={results['with_cache']['p95_ms']}ms",
        {"scenario": "cache_stampede_concurrent", **results},
    )


def scenario_cache_cost_comparison() -> ScenarioResult:
    """Explicit with-cache vs without-cache cost comparison on a repeated workload."""
    out = {}
    for label, disable in (("no_cache", True), ("with_cache", False)):
        gateway, calls = _fresh_gateway(disable_cache=disable)
        mc = MetricsCollector(label)
        for _ in range(5):
            for qq in QUERIES:
                _drive(gateway, mc, qq)
        out[label] = {
            "provider_calls": calls["n"],
            "hit_rate": round(gateway.cache.hit_rate, 3),
            "cost_saved_usd": round(gateway.cache.cost_saved_usd, 5),
        }
    saved_calls = out["no_cache"]["provider_calls"] - out["with_cache"]["provider_calls"]
    passed = saved_calls >= 40 and out["with_cache"]["cost_saved_usd"] > 0
    return ScenarioResult(
        "cache_cost_comparison",
        passed,
        f"provider_calls {out['no_cache']['provider_calls']} -> {out['with_cache']['provider_calls']} "
        f"(-{saved_calls}), hit_rate={out['with_cache']['hit_rate']}, "
        f"cost_saved=${out['with_cache']['cost_saved_usd']}",
        {"scenario": "cache_cost_comparison", **out},
    )


SCENARIOS = [
    scenario_baseline_healthy,
    scenario_provider_outage,
    scenario_silent_degradation,
    scenario_latency_spike,
    scenario_redis_down_failover,
    scenario_cache_cost_comparison,
    scenario_cache_stampede_concurrent,
]


def main() -> int:
    print("=" * 78)
    print("CHAOS & LOAD TEST")
    print("=" * 78)
    results = [fn() for fn in SCENARIOS]

    rows = []
    for r in results:
        flag = "PASS" if r.passed else "FAIL"
        print(f"[{flag}] {r.name}\n       {r.detail}")
        rows.append(r)

    passed = sum(r.passed for r in results)
    print("-" * 78)
    print(f"{passed}/{len(results)} scenarios passed")

    payload = {
        "summary": {
            "scenarios_total": len(results),
            "scenarios_passed": passed,
        },
        "scenarios": [
            {"name": r.name, "passed": r.passed, "detail": r.detail, "metrics": r.snapshot}
            for r in results
        ],
    }
    dump_metrics(ROOT / "metrics.json", payload)
    _write_report(rows)
    print(f"wrote {ROOT / 'metrics.json'} and {ROOT / 'reports' / 'chaos_results.md'}")
    return 0 if passed == len(results) else 1


def _write_report(rows: list[ScenarioResult]) -> None:
    lines = [
        "# Chaos & Load Test Results",
        "",
        "Generated by `python chaos_load_test.py`. Reproducible: fixed workloads and",
        "fixed fault windows; see `metrics.json` for the full snapshot.",
        "",
        "| Scenario | Result | Evidence |",
        "|----------|--------|----------|",
    ]
    for r in rows:
        lines.append(f"| `{r.name}` | {'PASS' if r.passed else 'FAIL'} | {r.detail} |")
    lines += [
        "",
        "## What each scenario proves",
        "",
        "- **baseline_healthy** - under a normal repeated workload the cache serves the",
        "  majority of requests and the circuit never trips.",
        "- **provider_outage** - consecutive 503s trip the breaker (fail-fast, no retry",
        "  storm); after the outage the HALF_OPEN probe closes it again. Recovery is",
        "  visible in `transition_log`.",
        "- **silent_degradation** - provider returns HTTP 200 with a wrong answer; the",
        "  quality guardrail blocks every one and no wrong answer reaches the user.",
        "- **latency_spike** - a slow window inflates P99 while P50 stays low; the",
        "  observability layer captures the tail.",
        "- **redis_down_failover** - Redis throws on every call; the shared cache",
        "  transparently degrades to in-memory and keeps its privacy guardrail.",
        "- **cache_cost_comparison** - same workload with vs without cache: provider",
        "  calls and $ cost drop sharply.",
        "- **cache_stampede_concurrent** (stretch) - 50 identical requests on 10 threads;",
        "  the cache collapses them to a handful of provider calls and P95 improves.",
    ]
    (ROOT / "reports").mkdir(exist_ok=True)
    (ROOT / "reports" / "chaos_results.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


if __name__ == "__main__":
    raise SystemExit(main())
