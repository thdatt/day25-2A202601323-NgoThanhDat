import json

from metrics import MetricsCollector, dump_metrics


def test_percentiles_availability_and_breakdown():
    mc = MetricsCollector("unit")
    # 100 requests: latencies 1..100 ms, 5 unavailable, 10 incorrect.
    for i in range(1, 101):
        mc.record_request(
            latency_ms=i,
            available=i > 5,
            correct=i > 10,
            served_from="primary" if i % 2 else "cache",
        )
    mc.record_circuit_open()

    snap = mc.snapshot(cache_stats={"hit_rate": 0.5})
    assert snap["requests"] == 100
    assert 49 <= snap["latency_ms"]["p50"] <= 51
    assert 94 <= snap["latency_ms"]["p95"] <= 96
    assert snap["latency_ms"]["max"] == 100.0
    assert snap["availability"] == 0.95
    assert snap["correctness"] == 0.90
    assert snap["circuit_open_count"] == 1
    assert snap["served_from"]["primary"] + snap["served_from"]["cache"] == 100
    assert snap["cache"] == {"hit_rate": 0.5}


def test_dump_metrics_is_valid_json(tmp_path):
    mc = MetricsCollector("io")
    mc.record_request(latency_ms=12.0, available=True, correct=True, served_from="primary")
    path = dump_metrics(tmp_path / "metrics.json", mc.snapshot())
    reloaded = json.loads(path.read_text(encoding="utf-8"))
    assert reloaded["scenario"] == "io"
    assert reloaded["requests"] == 1
