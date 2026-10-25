"""Generation seam — every LLM call goes through here.

Defaults point at local Ollama; any OpenAI-compatible provider (Z.ai, OpenAI…)
is a settings change away. Streaming is the norm; callers reassemble tokens.
"""

from collections.abc import AsyncIterator
from typing import Any

import litellm
from litellm import acompletion

from trust_rag.settings import get_settings

GROUNDING_SYSTEM_PROMPT = """You answer questions strictly from the provided context.

Rules:
- Use ONLY the numbered context passages. If they don't contain the answer,
  say: "I don't have enough information to answer this."
- Cite passages inline like [1] or [2] after each claim you use.
- Be concise and factual. Never invent policies, numbers, or names."""


async def acomplete_json(
    system: str, user: str, model: str | None = None
) -> Any:
    """Non-streaming LLM call that must answer with pure JSON.

    Returns None if the model didn't produce parseable JSON — callers decide
    how to degrade (verification treats a parse failure as unverifiable).
    """
    settings = get_settings()
    response = await acompletion(
        model=f"openai/{model or settings.verification_model}",
        api_base=settings.llm_api_base,
        api_key=settings.llm_api_key,
        temperature=0,  # extraction/verification must be deterministic
        messages=[
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        response_format={"type": "json_object"},
    )
    text = response.choices[0].message.content or ""
    import json

    try:
        return json.loads(_strip_json_fences(text))
    except ValueError:
        litellm.logger.warning("LLM returned unparseable JSON: %s", text[:200])
        return None


def _strip_json_fences(text: str) -> str:
    t = text.strip()
    if t.startswith("```"):
        t = t.removeprefix("```json").removeprefix("```").removesuffix("```")
    return t.strip()


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
        temperature=0,  # grounded answers must be deterministic
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
