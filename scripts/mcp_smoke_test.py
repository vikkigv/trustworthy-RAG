"""Live end-to-end check: spawn the MCP server over stdio and call tools
as a real MCP client would (Claude Desktop parity). Run from repo root:

    TRUSTRAG_API_KEY=trg_… uv run python scripts/mcp_smoke_test.py
"""

import asyncio
import os
import sys

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client


async def main() -> None:
    params = StdioServerParameters(
        command=sys.executable,
        args=["-m", "mcp_server"],
        env={**os.environ, "PYTHONUNBUFFERED": "1"},
    )
    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()

            tools = await session.list_tools()
            print("TOOLS:", [t.name for t in tools.tools])
            assert {t.name for t in tools.tools} == {
                "rag.search",
                "rag.get_document",
                "rag.verify_claim",
            }

            result = await session.call_tool(
                "rag.search",
                {"query": "vacation carry-over policy", "top_k": 3},
            )
            print("\nrag.search:", result.content[0].text[:300])

            result = await session.call_tool(
                "rag.search",
                {
                    "query": "vacation carry-over policy",
                    "top_k": 3,
                    "as_of": "2026-10-25",
                },
            )
            print("\nrag.search (as_of 2026-10-25):", result.content[0].text[:300])

            result = await session.call_tool("rag.get_document", {})
            print("\nrag.get_document:", result.content[0].text[:300])

            result = await session.call_tool(
                "rag.verify_claim",
                {"claim": "Employees can carry over five vacation days."},
            )
            print("\nrag.verify_claim:", result.content[0].text[:400])
    print("\nMCP smoke test OK")


if __name__ == "__main__":
    asyncio.run(main())
