# TrustRAG Codebase Tour — how to learn this codebase fast

> Reading order that follows **one question traveling through the system**.
> Total core code: ~2,100 lines (`trust_rag/`), ~950 (`api/`), ~250 (`mcp_server.py`),
> ~1,500 (`dashboard/`). You can genuinely read all of it in a few evenings.

## The 60-second mental model

A user asks a question. The system's job is to answer **only from the tenant's
documents, cite what it used, admit what it can't support, and remember how
documents change over time.**

```
upload ──► parse ──► chunk ──► embed ──► Postgres (pgvector + tsvector)
                                                      │
question ──────────────────────────────► hybrid_search│  (dense + BM25 → RRF)
        │                                          │
        ├─ (follow-up? rewrite to standalone)       │
        │                                          ▼
        │                                    context passages
        │                                          │
        │                                   qwen2.5:7b streams answer
        │                                          │
        └─ as_of date? ◄── validity windows ── verifier: claims → verdicts
                           (temporal)              │
                                                  confidence / abstain
```

Five ideas you must be able to explain on a whiteboard:

1. **Hybrid retrieval + RRF** — two rankings (vector similarity, keyword BM25)
   fused by `1/(60+rank)` — chunks found by *both* legs float up.
2. **Trust layer** — a second LLM pass splits the answer into atomic claims and
   checks each against the retrieved passages: verified / unsupported /
   contradicted. Confidence = `0.6×verified + 0.4×retrieval_strength`; below
   0.5 → refuse and explain.
3. **Temporal RAG** — re-uploading the same filename creates a version; old
   chunks get `valid_to`, new get `valid_from`. An `as_of` date retrieves only
   chunks whose validity window contains that instant.
4. **Tenant isolation** — `tenant_id` is filtered *inside* the SQL of both
   retrieval legs. Never post-filtered. This is the security story.
5. **MCP** — the same engine exposed as tools (`rag.search`, `rag.verify_claim`)
   that outside AI agents call over the Model Context Protocol.

## Reading order (each file answers one question)

### Stage 0 — orientation (30 min)
- `BUILD_PLAN.md` — the original design. Read the phases; you built them all.
- `docs/architecture.md` — diagrams + decisions table.
- Run the demo yourself: `docker compose up -d`, dashboard on :3001, ask a
  question, set the date picker, watch what changes.

### Stage 1 — how documents get in (~250 lines)
- `trust_rag/ingestion/chunker.py` (67 lines) — paragraph-aware packing. *Why
  paragraphs beat fixed slicing: keeps semantic units intact.*
- `trust_rag/ingestion/pipeline.py` — parse → chunk → embed → index,
  idempotent (delete-then-insert), **and the temporal cut-over**: when
  `supersedes_id` is set it closes the old version's chunks (`valid_to = now`).
- `trust_rag/embeddings.py` — one function through LiteLLM to Ollama `bge-m3`.
  Everything model-related goes through this seam — swap providers via env.

### Stage 2 — how questions get answered (the heart, ~400 lines)
- `trust_rag/retrieval/hybrid.py` (131 lines) — **read the SQL comment-first**.
  Two CTEs (dense rank, sparse rank), FULL OUTER JOIN, RRF in the SELECT, and
  the temporal `CASE` predicate at the bottom. This one file is the
  technical centerpiece — know every clause.
- `trust_rag/generation/llm.py` — the grounding prompt (cite [n], refuse if
  absent), `astream_answer` (temperature=0: determinism), and
  `rewrite_followup` (conversation memory).
- `trust_rag/verification/verifier.py` — claim extraction + entailment +
  the confidence formula + abstention. The differentiator; read twice.
- `api/routers/query.py` — orchestration + SSE event protocol
  (`retrieved → token… → claims → done`). Note the follow-up rewrite at the
  top and the changed-since comparison at the bottom.

### Stage 3 — platform around it (~700 lines)
- `trust_rag/db/models.py` — 11 tables; chunk carries embedding, tsvector,
  valid_from/valid_to, denormalized tenant_id. Data model = architecture.
- `trust_rag/security.py` + `api/core/deps.py` — bcrypt, JWT, `trg_` API keys
  (SHA-256 hashed), and the one `require_auth` chokepoint.
- `api/routers/documents.py` — upload + **version detection** (same filename +
  different checksum → supersedes). Delete cascades.
- `trust_rag/eval/harness.py` — the eval runs the real pipeline against a
  golden set; the verifier itself is the faithfulness scorer.

### Stage 4 — the surfaces (~1,800 lines, skim strategically)
- `mcp_server.py` (243 lines) — three `@server.tool` functions that call the
  same core. Read to see how little MCP glue a well-layered core needs.
- `dashboard/src/lib/api.ts` — the single seam: auth, fetch wrapper, **the SSE
  parser** (how a stream of events becomes UI state).
- `dashboard/src/app/(app)/chat/page.tsx` — the richest page: streaming turns,
  claim underlines, confidence gauge, temporal banner, per-turn sources.
- `api/routers/analytics.py`, dashboard page — stats queries, hand-rolled SVG chart.

### Stage 5 — tests as documentation (~1,400 lines)
Tests encode intended behavior better than comments. Best ones to read:
- `tests/test_retrieval.py` — deterministic fake vectors prove RRF + tenant
  isolation without any LLM.
- `tests/test_temporal.py` — validity-window semantics.
- `tests/test_eval.py` — how metrics are computed.
- `tests/test_rewrite.py` + `tests/test_mcp.py` — the two newest features.

## See it live (fastest teacher)

1. **Watch a query in Langfuse** (localhost:3000) — every stage is a span:
   followup-rewrite → hybrid-retrieval → grounded-answer → claim-verification.
2. **Watch the SQL** — pgAdmin (localhost:5050): `SELECT content, valid_from,
   valid_to FROM chunks WHERE tenant_id = '…'` — see version chains with your
   own eyes.
3. **Break it on purpose** — stop Ollama, ask a question, watch the error path.
   Restart, delete a document mid-chat. Understanding failure paths = confidence.
4. **`make eval`** — watch 20 questions run end-to-end in the real pipeline.

## The 8 concepts you didn't know coming in (learn these cold)

| Concept | Where | One-liner for interviews |
|---|---|---|
| RRF fusion | `hybrid.py` | "Two rankers, one score: 1/(k+rank), k=60" |
| BM25 / tsvector | `hybrid.py` sparse CTE | "Postgres native keyword relevance, not a separate engine" |
| Entailment verification | `verifier.py` | "A second pass checks each claim against its citations" |
| Abstention threshold | `verifier.py` | "Below 0.5 confidence the system refuses and explains" |
| Validity windows | `pipeline.py`, chunks | "Versions as half-open time intervals; as_of picks the version in force" |
| SSE streaming | `query.py` + `api.ts` | "retrieved → tokens → claims → done; citations arrive before the answer finishes" |
| Query rewriting | `llm.py` | "Follow-ups are condensed into standalone questions pre-retrieval" |
| MCP | `mcp_server.py` | "MCP is discovery+transport; the LLM routes on tool descriptions" |

## Presentation narrative (the story to tell)

1. **Problem**: LLM assistants hallucinate; RAG fixes grounding but not trust —
   answers still come without receipts, and policies *change*.
2. **Insight**: make verification a first-class stage, not an afterthought —
   and make time a query parameter.
3. **Walk the demo**: ask a question → cited, verified answer. Ask garbage →
   refusal with reason. Set a date → the *old* policy, plus "changed since"
   banner. Open Claude/ZCode → same engine via MCP.
4. **Numbers**: 61 tests, eval metrics all 1.00, everything on a 16 GB laptop
   with local models — deliberately zero paid API dependency.
5. **Depth flexes**: the one-SQL hybrid retrieval (CTEs + RRF + temporal CASE),
   tenant isolation inside the query, and the eval harness that caught a real
   retrieval leak during development (tell that story — it's true and it's in
   the git history).
