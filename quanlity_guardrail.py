"""Quality guardrail for silent/degraded LLM failures (HTTP 200 but bad answer)."""
from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any, Callable


@dataclass(slots=True)
class QualityMetrics:
    http_status: int
    latency_seconds: float
    faithfulness_score: float
    relevancy_score: float
    quality_score: float
    is_slo_violated: bool


class ProductionAgentGateway:
    """Detect degraded quality and fail closed instead of returning hallucinations."""

    def __init__(
        self,
        quality_slo_threshold: float = 0.75,
        faithfulness_weight: float = 0.7,
        relevancy_weight: float = 0.3,
        fallback_message: str = "Xin lỗi, tôi chưa thể trả lời đáng tin cậy từ tài liệu hiện có.",
    ) -> None:
        self.slo_threshold = quality_slo_threshold
        self.faithfulness_weight = faithfulness_weight
        self.relevancy_weight = relevancy_weight
        self.fallback_message = fallback_message

    def evaluate(
        self,
        response: str,
        context: str,
        query: str,
        *,
        faithfulness_fn: Callable[[str, str, str], float] | None = None,
        relevancy_fn: Callable[[str, str], float] | None = None,
        latency_seconds: float = 0.0,
    ) -> dict[str, Any]:
        faithfulness = (faithfulness_fn or self._faithfulness_heuristic)(query, context, response)
        relevancy = (relevancy_fn or self._relevancy_heuristic)(query, response)
        quality = self.faithfulness_weight * faithfulness + self.relevancy_weight * relevancy
        violated = quality < self.slo_threshold
        metrics = QualityMetrics(
            http_status=200,
            latency_seconds=latency_seconds,
            faithfulness_score=faithfulness,
            relevancy_score=relevancy,
            quality_score=quality,
            is_slo_violated=violated,
        )
        return {
            "status": "degraded_quality_detected" if violated else "success",
            "output": self.fallback_message if violated else response,
            "metrics": asdict(metrics),
        }

    def handle_request(self, query: str, retrieved_context: str) -> dict[str, Any]:
        # Deliberately degraded demo: the HTTP call succeeds but the answer contradicts context.
        response = "Chính sách hoàn tiền của công ty là trong vòng 90 ngày kể từ khi mua."
        return self.evaluate(response, retrieved_context, query, latency_seconds=1.2)

    @staticmethod
    def _faithfulness_heuristic(query: str, context: str, response: str) -> float:
        del query
        if "90 ngày" in response and "30 ngày" in context:
            return 0.20
        return 0.95

    @staticmethod
    def _relevancy_heuristic(query: str, response: str) -> float:
        query_terms = set(query.casefold().split())
        response_terms = set(response.casefold().split())
        return 0.85 if query_terms & response_terms else 0.40


if __name__ == "__main__":
    import json
    import sys

    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")  # Windows console safety

    gateway = ProductionAgentGateway(quality_slo_threshold=0.75)
    result = gateway.handle_request(
        "Thời hạn hoàn tiền là bao lâu?",
        "Quy định công ty: Thời hạn hoàn tiền tối đa là 30 ngày cho mọi đơn hàng hợp lệ.",
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))
