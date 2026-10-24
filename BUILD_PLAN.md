# TrustRAG — Trustworthy RAG Platform

A production-grade RAG platform that proves its answers: every claim is cited and
machine-verified, the system abstains when evidence is insufficient, and a built-in
evaluation harness measures whether changes actually improved answer quality.

## Pitch

> Answers you can trust because the app proves them — and a dashboard proving the
> app itself is measurably good.

## Locked-in stack decisions

| Decision | Choice |
|---|---|
| Vector store | **PostgreSQL + pgvector** (hybrid: dense + tsvector BM25) |
| Agent orchestration | **LangGraph** |
| LLM access | **LiteLLM** (swap models per stage, cost tracking) |
| Tracing | **Langfuse (self-hosted)** |
| Queue | **Arq** (async) + Redis |
| Frontend | **Next.js** (chat UI + dashboard) |
| Eval | **RAGAS** + golden dataset, run in GitHub Actions CI |
| Reranker | **bge-reranker-v2-m2** self-hosted (sentence-transformers) |
| Embeddings | OpenAI `text-embedding-3-small` |
| Infra | Docker Compose (dev) → AWS ECS Fargate + Terraform (prod) |
| Auth | JWT (users) + API keys (programmatic), multi-tenant collections |

## Architecture

```
Next.js ──► FastAPI (async, SSE streaming)
              ├──► LangGraph agent loop (v2.5)
              │      └──► tools: rag.search / rag.verify / MCP client (v3)
              ├──► LiteLLM ──► strong model (generation)
              │            ──► cheap model (verification / judging)
              ├──► Postgres + pgvector + tsvector (data + hybrid search)
              ├──► Redis (semantic cache, rate limits)
              ├──► Arq workers (ingestion pipeline)
              ├──► Langfuse (tracing: retrieval → rerank → gen → verify)
              └──► MCP server (v3, shares core package)
```

## Repo layout

```
ai-rag/
├── api/                  # FastAPI app: routers, schemas, auth, deps
│   ├── main.py
│   ├── routers/          # documents, query, eval, admin, health
│   └── core/             # config, security, sse helpers
├── core/                 # Shared python package "trust_rag"
│   ├── ingestion/        # parse → chunk → embed → index (Arq jobs)
│   ├── retrieval/        # hybrid search, reranking, filters
│   ├── generation/       # prompts, streaming, LiteLLM calls
│   ├── verification/     # claim extraction, entailment checks, confidence
│   ├── agent/            # LangGraph graph + tools (v2.5)
│   ├── eval/             # RAGAS harness, golden dataset loader, scoring
│   └── db/               # SQLAlchemy models, migrations (Alembic), repos
├── mcp_server/           # MCP server exposing rag.search etc. (v3)
├── evals/                # golden_dataset.jsonl + notebooks
├── dashboard/            # Next.js app (chat UI, citations, metrics)
├── infra/
│   ├── docker/           # Dockerfiles, docker-compose.yml
│   └── terraform/        # AWS ECS + RDS + ElastiCache
├── .github/workflows/    # CI: lint, test, evals-on-PR
└── docs/                 # architecture decisions (ADRs), diagrams
```

## Data model (Postgres)

```
tenants(id, name, created_at)
users(id, tenant_id, email, hashed_pw, role)
api_keys(id, tenant_id, key_hash, name, scopes)
documents(id, tenant_id, filename, mime, checksum, status, created_at)
chunks(id, document_id, tenant_id, content, chunk_index, embedding vector(1536),
       tsv tsvector, metadata jsonb, valid_from timestamptz, valid_to timestamptz)
       -- HNSW index on embedding, GIN on tsv; version chains for temporal queries
query_logs(id, tenant_id, question, answer, confidence, latency_ms,
           retrieved_chunk_ids jsonb, tokens_in, tokens_out, cost_usd, created_at)
claims(id, query_log_id, text, verdict, supporting_chunk_ids jsonb)  -- verified/unsupported
eval_runs(id, git_sha, config jsonb, created_at)
eval_scores(id, eval_run_id, metric, value)   -- faithfulness, relevance, precision, recall
ingestion_jobs(id, document_id, status, error, attempts)
```

Tenant isolation: every retrieval query filters `tenant_id` at the SQL level —
never post-filtered in application code. This is the RAG security showpiece.

## API contract (v1)

```
POST   /auth/token                      # JWT login
POST   /documents                       # multipart upload → enqueue ingestion
GET    /documents                       # list + status
GET    /documents/{id}
DELETE /documents/{id}
POST   /query                           # JSON: question, collection, mode
       → SSE stream: token events, then citations[], claims[], confidence
POST   /query:ab_test                   # run same q through two retrieval configs (v2)
GET    /evals/runs                      # score history for dashboard (v2)
GET    /evals/runs/{id}/details
GET    /traces/{query_log_id}           # Langfuse deep-link (v2)
GET    /health | /metrics               # prometheus format
```

Streaming protocol: SSE with typed events —
`token`, `retrieved` (chunk ids + scores), `citation`, `claim_verdict`, `done`
(frontend renders citations and flags as they arrive).

## Verification & abstention design (the core differentiator)

1. Generation returns answer sentences + citations.
2. Cheap model (via LiteLLM) runs claim extraction → entailment check per claim
   against its cited chunks → verdict: `verified | unsupported | contradicted`.
3. Confidence = weighted mix of retrieval scores + fraction of verified claims.
4. Policy: `unsupported` claims are flagged inline (or stripped in strict mode);
   confidence below threshold → abstain, return "insufficient evidence" with the
   retrieved context shown so the user sees *why*.
5. Every verdict is logged to `claims` — the eval harness re-scores these.

## Headline features (the differentiators)

1. **Trust layer** — machine-verified claims, inline citations, confidence-based
   abstention. Makes the answers credible.
2. **Temporal queries (time-travel RAG)** — query the knowledge base *as of a
   date*: "what was the carry-over policy before the March 2024 revision?"
   Handles document versioning, superseded chunks, and contradictions across
   versions. Rarely built, memorable demo. This is the unique hook.

## Phased roadmap

### v1 — Trustworthy pipeline — ✅ COMPLETE (2026-10-24, local; deploy split to 11b)
1. Repo scaffold, Docker Compose (api, postgres+pgvector, redis, arq, langfuse), CI skeleton
2. Auth: JWT + API keys, tenants
3. Ingestion: upload → Arq job → parse (pypdf/python-docx) → chunk → embed → index (pgvector + tsvector)
4. Hybrid retrieval: RRF fusion of dense + BM25, rerank top-50→10
5. Query endpoint: SSE streaming, citations, strict mode toggle
6. Verification pass + confidence + abstention
7. Langfuse tracing wired through every stage
8. Golden dataset (~50 Q/A pairs over 2–3 sample doc sets) + RAGAS in CI
9. README + architecture docs (done); deploy split out — see 11b

### v2 — Platform depth
- Dashboard: eval history, trace viewer, per-stage latency/cost
- A/B retrieval playground (compare configs on golden set)
- Query rewriting + multi-query expansion (measure the lift)
- Semantic caching (Redis, embedding similarity ≥ threshold; show hit-rate)
- Conversational memory (follow-up resolution)
- Ingestion diffing (checksum → re-chunk only changed sections, chunk versioning foundation)

### v2.5 — Temporal RAG (the unique hook)
- Chunk version chains: on re-upload, diff sections → new chunk versions supersede old ones
  (chunks get valid_from / valid_to; retrieval filters by `as_of` date)
- Temporal query mode: `POST /query { "as_of": "2024-03-01" }` — retrieve only chunks
  valid at that date; answers cite the version in effect
- Contradiction surfacing: "policy changed on X — old answer vs current answer"
  side-by-side with both citations
- Golden set extended with temporal questions; evals cover both modes

### v2.6 — Agentic mode

### v2.6 — Agentic mode
- LangGraph state machine: decompose → multi-search → detect conflicts → verify → synthesize
- Self-correction loop: verifier failure triggers targeted re-retrieval (max 2 hops)
- Evals prove agent mode vs pipeline mode lift in faithfulness/recall

### v3 — MCP
- MCP server exposing `rag.search`, `rag.get_document`, `rag.verify_claim` (shares core package)
- Agent consumes external MCP servers as pluggable tools
- Demo: query your RAG from Claude Desktop

### 11b — Deploy (optional, ~$15–40/mo or free-tier)
- Terraform → AWS ECS Fargate + RDS; live URL in README
- Swap local Ollama for a hosted provider (Z.ai/OpenAI) via env
- Free alternatives: Fly.io/Render free tier, Oracle Cloud free ARM

### Garnish (pick one, max)
- Table-aware PDF extraction
- Eval-score-drop Slack alerting
- Per-tenant token budgets

## Definition of done (per phase)

- v1: live URL + README GIF; eval scores reproducible from CI log; one-command local run
- v2: dashboard screenshots in README; A/B result table; cache hit-rate metric
- v2.5: live demo answering "as of <date>" questions with old-vs-new side-by-side citations
- v2.6: side-by-side eval table (pipeline vs agent) with traces for 3 example questions
- v3: 60-second demo of Claude Desktop answering from your documents via your MCP server
