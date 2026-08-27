# Day 25 — Circuit Breakers & Reliability Patterns for LLM Systems

## 1. Objective

This lab demonstrates a production reliability stack for LLM/agent systems:

`Semantic Cache -> Circuit Breaker -> Provider -> Retry + Jitter -> Quality Guardrail -> Fallback`

The implementation follows the concepts in the official Day 25 repository while adding repeatable unit tests and an integrated reliability gateway.

## 2. Implemented patterns

### Circuit Breaker

Three states are implemented: `CLOSED`, `OPEN`, and `HALF_OPEN`.

- `CLOSED`: calls pass through and expected failures are counted.
- `OPEN`: calls fail fast without hitting the unhealthy dependency.
- `HALF_OPEN`: after the reset timeout, probe calls test recovery.
- A successful probe closes the circuit; a failed probe reopens it.

### Semantic / Response Cache

Two cache layers are provided:

- `ResponseCache`: in-memory TTL cache with lightweight semantic similarity.
- `SharedRedisCache`: shared Redis cache for multi-instance deployments.

Guardrails:

- privacy-sensitive queries are not cached;
- entries expire via TTL;
- likely false hits with conflicting 4-digit years/IDs are rejected and logged.

### Fallback Ladder

The fallback ladder preserves a minimum output contract while degrading gracefully:

1. primary best model;
2. backup provider;
3. smaller/cheaper model;
4. cached response;
5. safe static fallback.

### Retry + Full Jitter

Only retryable infrastructure failures (`ConnectionError`, `TimeoutError`) are retried. The delay is bounded exponential backoff with Full Jitter. Programming/input errors are not retried.

### Quality Guardrail

A request can return HTTP 200 and still be unsafe or incorrect. The quality guardrail combines faithfulness and relevancy into a quality SLO and blocks responses that fall below the threshold.

### Integrated gateway

`reliability_gateway.py` wires the patterns together: semantic/response cache -> circuit breaker -> retry+jitter -> quality guardrail -> fallback ladder. It exposes four terminal statuses so an operator can tell them apart:

| status | meaning |
|--------|---------|
| `success` | answer came from the primary provider and passed the quality SLO |
| `cache_hit` | served from cache, provider not called |
| `degraded_quality_fallback` | provider returned HTTP 200 but failed the quality SLO; served from the fallback ladder |
| `degraded_provider_fallback` | provider was unreachable / circuit OPEN after retries; served from the fallback ladder |

The fallback ladder always returns *something*, and its own `status` field can read `"success"` for a lower tier. The gateway therefore does **not** forward that field verbatim — a degraded answer must never surface to callers/monitoring as `success`. `python reliability_gateway.py` walks all three failure branches.

## 3. Failure mode selected: DEGRADED

### Scenario

A customer-support RAG system retrieves a policy stating that refunds are allowed for **30 days**. The LLM provider is reachable and returns HTTP 200, but because of model drift, prompt regression, or overloaded inference it responds that the refund period is **90 days**.

This is not an availability outage. It is **silent quality degradation**.

### Why a normal circuit breaker is insufficient

A conventional circuit breaker sees:

- HTTP request succeeded;
- no connection exception;
- latency may still be acceptable.

Therefore it would treat the call as successful and return the hallucinated answer.

### Handling strategy

1. Provider returns an answer.
2. Quality guardrail computes faithfulness + relevancy.
3. If the combined quality score is below the SLO threshold, the response is blocked.
4. The request is routed to a feature-compatible fallback ladder.
5. The user receives a safe degraded response rather than incorrect information.
6. Repeated quality-SLO violations should be monitored separately and can be promoted into a quality-based circuit breaker in production.

### Expected behavior

For context `refund <= 30 days` and response `refund = 90 days`:

- HTTP status: `200`
- faithfulness: low
- quality SLO: violated
- unsafe answer: not returned
- fallback: activated

This behavior is covered by `tests/test_quality_guardrail.py` and `tests/test_integrated_gateway.py`.

## 4. Cache reliability findings

Caching improves latency and cost, but semantic caches create correctness/privacy risks.

Two explicit protections are implemented:

- private queries such as account/password/balance-related requests bypass cache;
- semantically similar queries containing different years/IDs are treated as possible false hits and are rejected.

Redis is optional for offline tests. `docker compose up -d` enables a shared cache for multi-instance deployment testing.

## 5. Evaluation

Offline correctness is validated with deterministic tests so API quota is not required for the core reliability patterns. All injected clocks / RNG / embedders make the suite fully repeatable.

```text
$ python -m pytest tests -q
15 passed

$ python scripts/run_all.py
... every offline demo runs ...
Offline checks complete. Use --live-eval after setting GOOGLE_API_KEY.
```

Coverage: circuit breaker open/recover + non-tripping exceptions; cache TTL/exact hit, privacy bypass, 4-digit false-hit guard; semantic-cache hit/miss with an injected embedder; fallback ladder tier-3 success and static tier-5; retry succeeds-after-N and does-not-retry-programming-error; quality guardrail blocks the degraded HTTP 200 and passes a good answer; integrated gateway for the quality-fallback, provider-outage, and cache-hit paths.

Live evaluation uses the official lab's Gemini path:

- Gemini embedding for semantic cache;
- DeepEval faithfulness;
- RAGAS faithfulness + answer relevancy.

Live scores must be generated locally with a valid `GOOGLE_API_KEY`; no live metric is fabricated in this report.

## 6. Reproduction

```powershell
py -3.11 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
python -m pytest tests -v      # expect: 15 passed
python scripts/run_all.py      # expect: no traceback, ends "Offline checks complete."
```

Optional Redis:

```powershell
docker compose up -d
```

Live Gemini evidence:

```powershell
$env:GOOGLE_API_KEY="<your-key>"
python scripts/run_all.py --live-eval
```

Do not commit `.env` or API keys.

## 7. Production improvements

- Use rolling-window error rate rather than only consecutive failures.
- Add concurrency limits for HALF_OPEN probes.
- Add per-provider circuit breakers and observability metrics.
- Replace local semantic scan with a vector index for large caches.
- Namespace caches by tenant/user/policy version.
- Version cache entries and invalidate on knowledge-base changes.
- Use real online evaluators for faithfulness/relevancy and monitor quality-SLO trends.
- Add tracing for cache hit rate, fallback tier, breaker transitions, retries, latency, and quality violations.

## 8. Conclusion

The main lesson is that reliability for LLM systems is broader than HTTP uptime. Circuit breakers protect availability, cache and fallback protect latency/continuity, retry+jitter handles temporary infrastructure failures, and quality guardrails protect against **degraded but technically successful** LLM responses.
