# Day 25 — Track 3: Reliability Engineering cho Production Agents

Submission for the VLearn Codelabs Day 25 Track 3 lab. Full analysis and the
grading-rubric mapping are in [`reports/lab_report.md`](reports/lab_report.md).

## Reliability flow

```text
User Request
    |
    v
Response Cache -- HIT --> cached response (+ $ saved counter)
    |
   MISS
    v
Provider Router -- budget >= 80% --> downgrade to cheapest named provider
    |
    v
Circuit Breaker -- OPEN --> fail fast --> Fallback Ladder
    |  (transition_log records every CLOSED/OPEN/HALF_OPEN hop)
 CLOSED / HALF_OPEN
    v
LLM Provider -- transient failure --> Retry + Full Jitter
    |
 HTTP 200
    v
Quality Guardrail -- SLO violation --> Fallback Ladder
    |
 pass
    v
Response  +  cache.set(query, answer)      [every request -> MetricsCollector -> metrics.json]
```

## Files

| File | Rubric category | Run it |
|---|---|---|
| `state_machine.py` | circuit breaker (25) | `python state_machine.py` |
| `provider_router.py` | circuit breaker / routing (25) + budget stretch | `python provider_router.py` |
| `fallback_ladder.py` | circuit breaker / fallback (25) | `python fallback_ladder.py` |
| `jitter.py` | no retry storm (25) | `python jitter.py` |
| `cache.py` | in-memory cache & cost (15) + Redis shared cache (15) | — |
| `semantic_cache.py` | (live) Gemini embedding cache | `python semantic_cache.py` |
| `quanlity_guardrail.py` | silent-degradation guard | `python quanlity_guardrail.py` |
| `reliability_gateway.py` | integrated end-to-end flow | `python reliability_gateway.py` |
| `metrics.py` | observability & metrics (15) | `python metrics.py` |
| `chaos_load_test.py` | chaos & load testing (15) -> writes `metrics.json` | `python chaos_load_test.py` |
| `redis_shared_demo.py` | Redis shared state + failover (15) | `python redis_shared_demo.py` |
| `eval_deepeval.py`, `eval_ragas.py` | (live) faithfulness / relevancy | needs `GOOGLE_API_KEY` |
| `scripts/run_all.py` | runs every offline demo + the test suite | `python scripts/run_all.py` |
| `tests/` | 30 deterministic tests (`conftest.py` puts repo root on `sys.path`) | `python -m pytest tests -v` |
| `reports/lab_report.md`, `reports/chaos_results.md` | report & code quality (15) | — |

## Setup (Windows PowerShell)

```powershell
py -3.11 -m venv .venv
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
```

## Offline verification

```powershell
python -m pytest tests -v      # expect: 30 passed
python chaos_load_test.py      # expect: 7/7 scenarios pass -> metrics.json + reports/chaos_results.md
python scripts/run_all.py      # runs every offline demo, then the test suite
```

`run_all.py` forces UTF-8 on its child processes, so the Vietnamese demo output
does not crash on a legacy Windows console codepage (cp1252).

## Redis shared cache

Tests and `redis_shared_demo.py` use an in-process `fakeredis` server, so **no
docker is required**. To verify against a real Redis:

```powershell
docker compose up -d
docker compose ps
$env:REDIS_URL="redis://localhost:6379/0"
python redis_shared_demo.py
```

## Real Gemini evaluation (supplementary — not in the rubric)

```powershell
$env:GOOGLE_API_KEY="your-key"
python scripts/run_all.py --live-eval
```

Or copy `.env.example` to `.env` and put the key there — `run_all.py` loads `.env`
for values not already set in the environment. The `--live-eval` steps run with
`allow_fail` so a Gemini quota error does not abort the whole run.

Never commit the API key. `.env` and `.env.*` are git-ignored (`.env.example` is not).
