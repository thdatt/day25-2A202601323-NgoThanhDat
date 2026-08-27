"""Live RAGAS faithfulness + answer relevancy evaluation using Gemini."""
from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path

_RESULTS_PATH = Path(__file__).with_name("reports") / "ragas_results.json"


DATA = [
    (
        "Thời hạn hoàn tiền của tôi là bao lâu?",
        "Chính sách hoàn tiền là trong vòng 90 ngày kể từ khi mua.",
        ["Quy định công ty: Thời hạn hoàn tiền tối đa là 30 ngày."],
    ),
    (
        "Công ty có hỗ trợ giao hàng hỏa tốc không?",
        "Có, chúng tôi hỗ trợ giao hàng hỏa tốc nội thành trong 2 giờ.",
        ["Dịch vụ vận chuyển: Giao hàng hỏa tốc nội thành nhận hàng trong 2 giờ."],
    ),
]


def _shim_langchain_vertexai() -> None:
    """ragas (<=0.4.3) hard-imports ``langchain_community.chat_models.vertexai``,
    a module removed in langchain-community 0.4. It is only referenced in an
    ``isinstance`` list we never reach (Gemini is driven through the
    OpenAI-compatible client below), so a tiny stub lets ``import ragas`` succeed.
    """
    import sys
    import types

    name = "langchain_community.chat_models.vertexai"
    if name in sys.modules:
        return
    try:
        __import__(name)
        return
    except ModuleNotFoundError:
        pass
    stub = types.ModuleType(name)
    stub.ChatVertexAI = type("ChatVertexAI", (), {})  # placeholder, never instantiated
    sys.modules[name] = stub


async def evaluate_samples() -> list[dict[str, float | str]]:
    api_key = os.getenv("GOOGLE_API_KEY")
    if not api_key:
        raise RuntimeError("GOOGLE_API_KEY is required")

    _shim_langchain_vertexai()

    from google import genai
    from openai import AsyncOpenAI
    from ragas.embeddings import GoogleEmbeddings
    from ragas.llms import llm_factory
    from ragas.metrics.collections import AnswerRelevancy, Faithfulness

    llm_client = AsyncOpenAI(
        api_key=api_key,
        base_url="https://generativelanguage.googleapis.com/v1beta/openai/",
    )
    # RAGAS collections make many judge calls per sample; gemini-2.5-flash free
    # tier is only 20 req/day. gemini-3.5-flash-lite has a much larger free quota
    # and is what the recorded numbers in reports/ragas_results.json were run on.
    # Override with RAGAS_MODEL=gemini-2.5-flash to match eval_deepeval.py.
    model = os.getenv("RAGAS_MODEL", "gemini-3.5-flash-lite")
    llm = llm_factory(model, client=llm_client, max_tokens=4096)
    embeddings = GoogleEmbeddings(client=genai.Client(api_key=api_key))
    faithfulness = Faithfulness(llm=llm)
    relevancy = AnswerRelevancy(llm=llm, embeddings=embeddings)

    async def _score(coro_factory, tries: int = 5, cooldown: float = 62.0):
        """Retry around Gemini free-tier 429s (5 requests/minute)."""
        last: Exception | None = None
        for attempt in range(tries):
            try:
                return await coro_factory()
            except Exception as exc:  # openai.RateLimitError and friends
                if "429" not in str(exc) and "RESOURCE_EXHAUSTED" not in str(exc):
                    raise
                last = exc
                if attempt < tries - 1:
                    print(f"  rate limited, waiting {cooldown:.0f}s (attempt {attempt + 1}/{tries})")
                    await asyncio.sleep(cooldown)
        raise last  # type: ignore[misc]

    rows: list[dict[str, float | str]] = []
    for i, (question, answer, contexts) in enumerate(DATA):
        faith = await _score(
            lambda: faithfulness.ascore(
                user_input=question, response=answer, retrieved_contexts=contexts
            )
        )
        await asyncio.sleep(13)  # stay under 5 req/min
        rel = await _score(lambda: relevancy.ascore(user_input=question, response=answer))
        if i < len(DATA) - 1:
            await asyncio.sleep(13)
        rows.append(
            {
                "user_input": question,
                "faithfulness": round(float(faith.value), 4),
                "answer_relevancy": round(float(rel.value), 4),
            }
        )
        # Persist after every row so quota/console errors never lose results.
        _RESULTS_PATH.write_text(json.dumps(rows, indent=2, ensure_ascii=False), encoding="utf-8")
    return rows


def main() -> None:
    if not os.getenv("GOOGLE_API_KEY"):
        raise SystemExit("GOOGLE_API_KEY is required. Never commit it.")
    import sys

    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")  # Windows console safety
    _RESULTS_PATH.parent.mkdir(exist_ok=True)

    import pandas as pd

    rows = asyncio.run(evaluate_samples())
    print(pd.DataFrame(rows).to_string(index=False))
    print(f"\nsaved -> {_RESULTS_PATH}")


if __name__ == "__main__":
    main()
