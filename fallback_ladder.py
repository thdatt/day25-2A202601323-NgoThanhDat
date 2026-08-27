"""Feature-compatible fallback ladder for an LLM gateway."""
from __future__ import annotations

from typing import Any, Callable


REQUIRED_FIELDS = {"intent": str, "confidence": (int, float), "reply": str}


def _validate_schema(data: Any) -> bool:
    if not isinstance(data, dict):
        return False
    return all(
        key in data and isinstance(data[key], expected)
        for key, expected in REQUIRED_FIELDS.items()
    )


class FallbackLadderAgent:
    def __init__(
        self,
        primary: Callable[[str], dict[str, Any]] | None = None,
        backup: Callable[[str], dict[str, Any]] | None = None,
        smaller: Callable[[str], dict[str, Any]] | None = None,
        cache: Callable[[str], dict[str, Any] | None] | None = None,
    ) -> None:
        self.primary = primary or self._primary_demo
        self.backup = backup or self._backup_demo
        self.smaller = smaller or self._smaller_demo
        self.cache = cache or self._cache_demo

    def execute(self, prompt: str) -> dict[str, Any]:
        tiers = [
            ("Tier 1: Primary Best Model", self.primary),
            ("Tier 2: Backup Provider", self.backup),
            ("Tier 3: Smaller/Cheaper Model", self.smaller),
        ]
        errors: list[str] = []
        for name, provider in tiers:
            try:
                result = provider(prompt)
            except Exception as exc:
                errors.append(f"{name}: {type(exc).__name__}: {exc}")
                continue
            if _validate_schema(result):
                return {"source": name, "status": "success", "data": result, "errors": errors}
            errors.append(f"{name}: incompatible output schema")

        cached = self.cache(prompt)
        if cached is not None and _validate_schema(cached):
            return {"source": "Tier 4: Cache", "status": "degraded_cached", "data": cached, "errors": errors}

        return {
            "source": "Tier 5: Static Fallback",
            "status": "hard_degraded",
            "data": {
                "intent": "unknown",
                "confidence": 0.0,
                "reply": "Hệ thống AI đang tạm suy giảm. Yêu cầu đã được ghi nhận; vui lòng thử lại sau hoặc liên hệ hỗ trợ.",
            },
            "errors": errors,
        }

    @staticmethod
    def _primary_demo(_: str) -> dict[str, Any]:
        raise TimeoutError("Primary provider timeout")

    @staticmethod
    def _backup_demo(_: str) -> dict[str, Any]:
        raise ConnectionError("Backup provider rate limited")

    @staticmethod
    def _smaller_demo(_: str) -> dict[str, Any]:
        return {"intent": "refund_request", "confidence": 0.82, "reply": "Tôi có thể hỗ trợ yêu cầu hoàn tiền."}

    @staticmethod
    def _cache_demo(_: str) -> dict[str, Any] | None:
        return {"intent": "refund_request", "confidence": 0.70, "reply": "Chính sách hoàn tiền áp dụng trong 30 ngày."}


if __name__ == "__main__":
    import json
    import sys

    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")  # Windows console safety

    print(json.dumps(FallbackLadderAgent().execute("Tôi muốn hoàn tiền"), ensure_ascii=False, indent=2))
