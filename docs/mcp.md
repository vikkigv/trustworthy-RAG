# TrustRAG MCP Server

Exposes TrustRAG's retrieval, documents, and trust layer as
[Model Context Protocol](https://modelcontextprotocol.io) tools, so external
AI agents (Claude Desktop, IDE agents, custom clients) can ground their
answers in your documents — with citations, temporal time-travel, and
machine verification.

## Tools

| Tool | What it does |
|---|---|
| `rag.search` | Hybrid dense+BM25 search. Optional `as_of` (ISO date) retrieves knowledge valid at that instant — time travel. |
| `rag.get_document` | List all documents (with version chains), or read one document's chunks. |
| `rag.verify_claim` | Verify a statement against the documents: per-claim verdicts (verified / unsupported / contradicted) + confidence. Abstain below 0.5 means "don't assert this". |

## Auth

The server is tenant-scoped, like the REST API. Create an API key
(`POST /auth/api-keys` or the dashboard) and pass it as `TRUSTRAG_API_KEY`.
Retrieval filters on `tenant_id` inside the SQL — one tenant's key can
never see another tenant's chunks.

## Running

```bash
TRUSTRAG_API_KEY=trg_… uv run python -m mcp_server   # stdio transport
```

Smoke test (spawns the server and calls every tool as a real MCP client):

```bash
TRUSTRAG_API_KEY=trg_… uv run python scripts/mcp_smoke_test.py
```

## Claude Desktop config

`~/Library/Application Support/Claude/claude_desktop_config.json`:

```json
{
  "mcpServers": {
    "trustrag": {
      "command": "uv",
      "args": [
        "run", "--directory", "/absolute/path/to/trustworthy-RAG",
        "python", "-m", "mcp_server"
      ],
      "env": {
        "TRUSTRAG_API_KEY": "trg_…"
      }
    }
  }
}
```

Then ask Claude: *"What's our vacation carry-over policy — and what did it
used to be?"* — watch it call `rag.search` twice (current + `as_of`) and
`rag.verify_claim` before answering.

## Notes

- stdio transport (local, no HTTP surface); streamable-http is available
  via `server.run(transport="streamable-http")` for remote deployments.
- Embeddings/generation go through the same LiteLLM seam as the REST API
  (local Ollama by default).
