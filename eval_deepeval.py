"""Live DeepEval faithfulness evaluation using Gemini."""
from __future__ import annotations

import os


def main() -> None:
    if not os.getenv("GOOGLE_API_KEY"):
        raise SystemExit("GOOGLE_API_KEY is required. Put it in the environment; never commit the key.")

    from deepeval.metrics import FaithfulnessMetric
    from deepeval.models import GeminiModel
    from deepeval.test_case import LLMTestCase

    test_case = LLMTestCase(
        input="Thời hạn hoàn tiền của tôi là bao lâu?",
        actual_output="Chính sách hoàn tiền của công ty là trong vòng 90 ngày.",
        retrieval_context=["Quy định công ty: Thời hạn hoàn tiền tối đa là 30 ngày cho mọi đơn hàng."],
    )
    metric = FaithfulnessMetric(threshold=0.7, model=GeminiModel(model="gemini-2.5-flash"))
    metric.measure(test_case)
    print(f"Faithfulness Score: {metric.score}")
    print(f"Pass SLO: {metric.is_successful()}")
    print(f"Reason: {metric.reason}")


if __name__ == "__main__":
    main()
