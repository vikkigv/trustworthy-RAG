"""Generation seam — every LLM call goes through here.

Defaults point at local Ollama; any OpenAI-compatible provider (Z.ai, OpenAI…)
is a settings change away. Streaming is the norm; callers reassemble tokens.
"""

from collections.abc import AsyncIterator

from litellm import acompletion

from trust_rag.settings import get_settings

GROUNDING_SYSTEM_PROMPT = """You answer questions strictly from the provided context.

Rules:
- Use ONLY the numbered context passages. If they don't contain the answer,
  say: "I don't have enough information to answer this."
- Cite passages inline like [1] or [2] after each claim you use.
- Be concise and factual. Never invent policies, numbers, or names."""


def build_context(chunks: list) -> str:
    """Render retrieved chunks as numbered context passages."""
    return "\n\n".join(
        f"[{i + 1}] {chunk.content}" for i, chunk in enumerate(chunks)
    )


async def astream_answer(
    question: str, context: str, model: str | None = None
) -> AsyncIterator[str]:
    """Stream grounded answer tokens for a question over pre-retrieved context."""
    settings = get_settings()
    response = await acompletion(
        model=f"openai/{model or settings.generation_model}",
        api_base=settings.llm_api_base,
        api_key=settings.llm_api_key,
        stream=True,
        messages=[
            {"role": "system", "content": GROUNDING_SYSTEM_PROMPT},
            {
                "role": "user",
                "content": f"Context passages:\n\n{context}\n\nQuestion: {question}",
            },
        ],
    )
    async for chunk in response:
        delta = chunk.choices[0].delta.content if chunk.choices else None
        if delta:
            yield delta
