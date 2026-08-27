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


def run(label: str, *cmd: str) -> None:
    # flush=True so these headers land before the child's inherited stdout.
    print("\n" + "=" * 70, flush=True)
    print(label, flush=True)
    print("=" * 70, flush=True)
    subprocess.run([sys.executable, *cmd], cwd=ROOT, check=True, env=CHILD_ENV)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--live-eval", action="store_true", help="also run Gemini semantic/evaluation scripts")
    args = parser.parse_args()

    run("Circuit Breaker", "state_machine.py")
    run("Fallback Ladder", "fallback_ladder.py")
    run("Exponential Backoff + Full Jitter", "jitter.py")
    run("Quality Guardrail - degraded failure", "quanlity_guardrail.py")
    run("Integrated Reliability Gateway", "reliability_gateway.py")
    run("Unit tests", "-m", "pytest", "tests", "-q")

    if args.live_eval:
        if not os.getenv("GOOGLE_API_KEY"):
            raise SystemExit("--live-eval requires GOOGLE_API_KEY")
        run("Gemini Semantic Cache", "semantic_cache.py")
        run("DeepEval", "eval_deepeval.py")
        run("RAGAS", "eval_ragas.py")
    else:
        print("\nOffline checks complete. Use --live-eval after setting GOOGLE_API_KEY.")


if __name__ == "__main__":
    main()
