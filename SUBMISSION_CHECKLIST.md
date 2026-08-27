# Submission Checklist — Day 25 Track 3

## Rubric coverage (thang điểm 100)

- [x] **Circuit breaker & fallback (25)** — 3-state machine (`CLOSED/OPEN/HALF_OPEN`),
  fail-fast while OPEN, bounded HALF_OPEN probe, no retry storm (jitter only retries
  transient infra errors; `CircuitOpenError` is not retryable), `provider_router.py`
  routes by **named** provider, `state_machine.py` keeps a `transition_log` + `open_count`.
- [x] **In-memory cache & cost (15)** — measured hit rate, `tokens_saved` / `cost_saved_usd`,
  TTL + similarity-threshold rationale (report §8), real false-hit example (4-digit
  year/ID mismatch, logged).
- [x] **Redis shared cache (15)** — `get`/`set` over `SharedRedisCache`, shared-state
  proof across two instances, privacy + false-hit guardrails intact cross-instance,
  5 passing Redis tests via `fakeredis` (no docker), transparent fallback to in-memory
  when Redis is down.
- [x] **Observability & metrics (15)** — `metrics.py` -> `metrics.json` with latency
  P50/P95/P99, availability, correctness, `circuit_open_count`, cache stats; reproducible.
- [x] **Chaos & load testing (15)** — `chaos_load_test.py`: 7 named scenarios, explicit
  PASS/FAIL, recovery evidence (`transition_log`), with-cache vs without-cache comparison.
- [x] **Report & code quality (15)** — architecture diagram, config table with rationale,
  weakness analysis, SLO table, full type hints, `30 passed`.

## Stretch goals

- [x] `ThreadPoolExecutor` concurrent load + changed metrics (`cache_stampede_concurrent`)
- [x] Cache auto-falls back to in-memory when Redis is down
- [x] Budget-based routing (spend >= 80% -> cheapest provider)
- [x] `hypothesis` property-based fuzzing of the state machine
- [x] SLO table + adherence check (report §9)
- [ ] Circuit state stored in Redis for multi-instance sync — documented as future work

## Run locally before submitting

1. `python -m pip install -r requirements.txt`
2. `python -m pytest tests -v`     -> `30 passed`
3. `python chaos_load_test.py`     -> `7/7 scenarios passed`, regenerates `metrics.json`
4. `python scripts/run_all.py`     -> every offline demo, no traceback
5. (optional) `docker compose up -d` then `$env:REDIS_URL=...; python redis_shared_demo.py`
6. (optional, supplementary) `$env:GOOGLE_API_KEY=...; python scripts/run_all.py --live-eval`
7. Confirm `.env` is NOT staged: `git status` should show only `.env.example`.

## Expected offline result

- `python -m pytest tests -v` -> `30 passed`
- `python chaos_load_test.py` -> `7/7 scenarios passed`
- `python scripts/run_all.py` -> ends `Offline checks complete.`, exit 0
