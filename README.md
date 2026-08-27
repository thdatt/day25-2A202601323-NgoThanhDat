# Day 25 — Circuit Breakers & Reliability Patterns for LLM Systems

Submission-ready implementation based on the official `VinUni-AI20k/day25-circuit-breakers` lab.

## Reliability flow

```text
User Request
    |
    v
Semantic Cache -- HIT --> cached response
    |
   MISS
    v
Circuit Breaker -- OPEN --> Fallback Ladder
    |
 CLOSED / HALF_OPEN
    v
LLM Provider -- transient failure --> Retry + Full Jitter
    |
 success
    v
Quality Guardrail -- SLO violation --> Fallback Ladder
    |
 pass
    v
Response
```

## Files

- `state_machine.py` — CLOSED / OPEN / HALF_OPEN circuit breaker (`python state_machine.py`)
- `cache.py` — in-memory + Redis cache, privacy and false-hit guards
- `semantic_cache.py` — Gemini embedding semantic cache (live)
- `fallback_ladder.py` — model/cache/static graceful degradation (`python fallback_ladder.py`)
- `jitter.py` — exponential backoff + Full Jitter (`python jitter.py`)
- `quanlity_guardrail.py` — silent-degradation quality SLO guard (`python quanlity_guardrail.py`)
- `reliability_gateway.py` — integrated end-to-end flow with runnable demo (`python reliability_gateway.py`)
- `eval_deepeval.py` — live DeepEval/Gemini faithfulness
- `eval_ragas.py` — live RAGAS/Gemini faithfulness + relevancy
- `scripts/run_all.py` — one command that runs every offline demo + the test suite
- `reports/lab_report.md` — lab analysis; selected failure mode: `degraded`
- `tests/` — 15 deterministic offline tests; `conftest.py` puts the repo root on `sys.path`
- `.env.example` — copy to `.env` (git-ignored) for the live path

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
python -m pytest tests -v      # expect: 15 passed
python scripts/run_all.py      # runs every offline demo, then the test suite
```

`run_all.py` forces UTF-8 on its child processes, so the Vietnamese demo output
does not crash on a legacy Windows console codepage (cp1252).

## Redis shared cache (optional)

```powershell
docker compose up -d
docker compose ps
```

## Real Gemini evaluation

The official repository requires a Google API key for embeddings and evaluation.

```powershell
$env:GOOGLE_API_KEY="your-key"
python scripts/run_all.py --live-eval
```

Alternatively, copy `.env.example` to `.env` and put the key there — `run_all.py`
loads `.env` for values that are not already set in the environment.

Never commit the API key. `.env` and `.env.*` are git-ignored (`.env.example` is not).
