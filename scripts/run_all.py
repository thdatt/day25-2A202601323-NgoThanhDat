from __future__ import annotations

import argparse
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

# Vietnamese demo output must not crash on a legacy Windows console codepage
# (cp1252). Force UTF-8 for this process and every child it spawns.
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")


def _load_dotenv(path: Path) -> None:
    """Minimal, dependency-free .env loader: fills vars that are not already set."""
    if not path.is_file():
        return
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key, value = key.strip(), value.strip().strip('"').strip("'")
        if key and key not in os.environ:
            os.environ[key] = value


_load_dotenv(ROOT / ".env")
CHILD_ENV = {**os.environ, "PYTHONUTF8": "1", "PYTHONIOENCODING": "utf-8"}


def run(label: str, *cmd: str, allow_fail: bool = False) -> None:
    # flush=True so these headers land before the child's inherited stdout.
    print("\n" + "=" * 70, flush=True)
    print(label, flush=True)
    print("=" * 70, flush=True)
    completed = subprocess.run([sys.executable, *cmd], cwd=ROOT, env=CHILD_ENV)
    if completed.returncode != 0:
        if allow_fail:
            print(f"[warn] {label} exited {completed.returncode} (continuing)", flush=True)
        else:
            raise SystemExit(f"{label} failed (exit {completed.returncode})")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--live-eval", action="store_true", help="also run Gemini semantic/evaluation scripts")
    args = parser.parse_args()

    run("Circuit Breaker + transition_log", "state_machine.py")
    run("Provider Router (named providers + budget)", "provider_router.py")
    run("Fallback Ladder", "fallback_ladder.py")
    run("Exponential Backoff + Full Jitter", "jitter.py")
    run("Quality Guardrail - degraded failure", "quanlity_guardrail.py")
    run("Integrated Reliability Gateway", "reliability_gateway.py")
    run("Redis Shared Cache (shared state + failover)", "redis_shared_demo.py")
    run("Chaos & Load Test -> metrics.json", "chaos_load_test.py")
    run("Unit tests", "-m", "pytest", "tests", "-q")

    if args.live_eval:
        if not os.getenv("GOOGLE_API_KEY"):
            raise SystemExit("--live-eval requires GOOGLE_API_KEY")
        run("Gemini Semantic Cache", "semantic_cache.py", allow_fail=True)
        run("DeepEval", "eval_deepeval.py", allow_fail=True)
        run("RAGAS", "eval_ragas.py", allow_fail=True)
    else:
        print("\nOffline checks complete. Use --live-eval after setting GOOGLE_API_KEY.")


if __name__ == "__main__":
    main()
