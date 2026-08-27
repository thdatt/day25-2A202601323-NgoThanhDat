# Submission Checklist — Day 25

## Already completed in this package

- [x] Circuit breaker state machine: CLOSED -> OPEN -> HALF_OPEN -> CLOSED
- [x] Fail-fast behavior while OPEN
- [x] Bounded recovery probe
- [x] In-memory response cache with TTL
- [x] Privacy-sensitive cache bypass
- [x] Semantic false-hit guard for conflicting years/IDs
- [x] Shared Redis cache implementation
- [x] Fallback ladder with schema compatibility
- [x] Exponential backoff + Full Jitter
- [x] Quality guardrail for HTTP-200 silent degradation
- [x] Integrated reliability gateway with a runnable end-to-end demo
- [x] Provider-outage path reports a distinct degraded status (not `success`)
- [x] 15 offline deterministic unit tests
- [x] `scripts/run_all.py` runs every offline demo + tests, UTF-8 safe on Windows
- [x] Lab report for failure mode `degraded`
- [x] DeepEval and RAGAS live-evaluation scripts

## You must do locally

1. Create/activate a Python 3.10+ virtual environment.
2. Install `requirements.txt`.
3. Run `python -m pytest tests -v`.
4. Run `python scripts/run_all.py`.
5. If your lab requires live Gemini evidence, configure `GOOGLE_API_KEY` and run `python scripts/run_all.py --live-eval`.
6. If Redis evidence is requested, run `docker compose up -d`, then verify `docker compose ps` shows Redis healthy.
7. Review `reports/lab_report.md` and replace/add any instructor-specific metadata requested in VLearn.
8. Confirm `.env` / API keys are not staged before pushing.

## Expected offline result

`15 passed` (from `python -m pytest tests -v`)
`python scripts/run_all.py` finishes with `Offline checks complete.` and no traceback.

## API requirement

The official lab README requires `GOOGLE_API_KEY` for Gemini embeddings and LLM evaluation. Offline reliability tests do not require a key.
