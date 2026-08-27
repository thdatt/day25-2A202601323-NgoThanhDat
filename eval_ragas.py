"""Live RAGAS faithfulness + answer relevancy evaluation using Gemini."""
from __future__ import annotations

import asyncio
import os


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


async def evaluate_samples() -> list[dict[str, float | str]]:
    api_key = os.getenv("GOOGLE_API_KEY")
    if not api_key:
        raise RuntimeError("GOOGLE_API_KEY is required")

    from google import genai
    from openai import AsyncOpenAI
    from ragas.embeddings import GoogleEmbeddings
    from ragas.llms import llm_factory
    from ragas.metrics.collections import AnswerRelevancy, Faithfulness

    llm_client = AsyncOpenAI(
        api_key=api_key,
        base_url="https://generativelanguage.googleapis.com/v1beta/openai/",
    )
    llm = llm_factory("gemini-2.5-flash", client=llm_client, max_tokens=4096)
    embeddings = GoogleEmbeddings(client=genai.Client(api_key=api_key))
    faithfulness = Faithfulness(llm=llm)
    relevancy = AnswerRelevancy(llm=llm, embeddings=embeddings)

    rows: list[dict[str, float | str]] = []
    for question, answer, contexts in DATA:
        faith = await faithfulness.ascore(
            user_input=question,
            response=answer,
            retrieved_contexts=contexts,
        )
        rel = await relevancy.ascore(user_input=question, response=answer)
        rows.append(
            {
                "user_input": question,
                "faithfulness": float(faith.value),
                "answer_relevancy": float(rel.value),
            }
        )
    return rows


def main() -> None:
    if not os.getenv("GOOGLE_API_KEY"):
        raise SystemExit("GOOGLE_API_KEY is required. Never commit it.")
    import pandas as pd

    print(pd.DataFrame(asyncio.run(evaluate_samples())).to_string(index=False))


if __name__ == "__main__":
    main()
