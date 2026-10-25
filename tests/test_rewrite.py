"""Follow-up rewriting tests — LLM mocked, no network."""

from unittest.mock import AsyncMock, patch

from trust_rag.generation.llm import REWRITE_SYSTEM_PROMPT, rewrite_followup

HISTORY = [
    {"question": "How many vacation days can I carry over?", "answer": "Five days [1]."},
]


async def test_rewrite_resolves_followup():
    with patch(
        "trust_rag.generation.llm.acomplete_json",
        AsyncMock(return_value={"standalone_question": "How many sick days can I carry over?"}),
    ) as mock:
        result = await rewrite_followup("What about sick days?", HISTORY)

    assert result == "How many sick days can I carry over?"
    # The prompt must carry the conversation and the latest question.
    sent = mock.call_args.args
    assert sent[0] == REWRITE_SYSTEM_PROMPT
    assert "How many vacation days" in sent[1]
    assert "What about sick days?" in sent[1]


async def test_rewrite_returns_none_on_bad_json():
    with patch(
        "trust_rag.generation.llm.acomplete_json", AsyncMock(return_value=None)
    ):
        assert await rewrite_followup("What about it?", HISTORY) is None


async def test_rewrite_returns_none_on_empty_string():
    with patch(
        "trust_rag.generation.llm.acomplete_json",
        AsyncMock(return_value={"standalone_question": "   "}),
    ):
        assert await rewrite_followup("What about it?", HISTORY) is None


async def test_rewrite_uses_only_last_four_turns():
    long_history = [
        {"question": f"q{i}", "answer": f"a{i}"} for i in range(8)
    ]
    with patch(
        "trust_rag.generation.llm.acomplete_json",
        AsyncMock(return_value={"standalone_question": "resolved"}),
    ) as mock:
        await rewrite_followup("and the next one?", long_history)

    transcript = mock.call_args.args[1]
    assert "q4" in transcript  # last four: q4..q7
    assert "q3" not in transcript
