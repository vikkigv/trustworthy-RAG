# TrustRAG

A trustworthy RAG platform: verified claims with inline citations, confidence-based
abstention, evals in CI, and temporal ("time-travel") queries.

See [BUILD_PLAN.md](BUILD_PLAN.md) for architecture, data model, API contract,
and the phased roadmap.

## Quickstart

```bash
cp .env.example .env        # add your OPENAI_API_KEY
make install                # uv sync
make compose-up             # postgres+pgvector, redis, api, worker
curl localhost:8000/health  # {"status":"ok"}
```

API docs: http://localhost:8000/docs

## Status

- [x] Scaffold: FastAPI skeleton, compose stack, CI
- [ ] v1 — trustworthy pipeline (auth → ingestion → hybrid retrieval → verification → evals → deploy)
- [ ] v2 — dashboard, A/B playground, semantic cache
- [ ] v2.5 — temporal RAG
- [ ] v2.6 — agentic mode (LangGraph)
- [ ] v3 — MCP server
