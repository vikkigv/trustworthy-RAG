"""TrustRAG MCP server — expose retrieval, documents, and the trust layer
as tools for external AI agents (Claude Desktop, IDE agents, …).

Runs over stdio; tenant identity comes from a TrustRAG API key (trg_…)
supplied via the TRUSTRAG_API_KEY environment variable. Every tool is
tenant-scoped exactly like the REST API — the SQL-level tenant filter in
hybrid_search is the isolation boundary.

Run:  TRUSTRAG_API_KEY=trg_… uv run python -m mcp_server
"""

import datetime as dt
import uuid

from mcp.server.mcpserver import MCPServer
from mcp.types import ToolAnnotations
from sqlalchemy import select

from trust_rag.db.models import ApiKey, Chunk, Document
from trust_rag.db.session import get_session_factory, init_engine
from trust_rag.retrieval.hybrid import hybrid_search
from trust_rag.security import hash_api_key
from trust_rag.settings import get_settings
from trust_rag.verification.verifier import verify_answer

server = MCPServer(
    name="trustrag",
    title="TrustRAG",
    description=(
        "Trustworthy RAG over your documents: hybrid dense+BM25 retrieval "
        "with temporal time-travel, document versions, and machine "
        "verification of claims."
    ),
    instructions=(
        "Use rag.search to find passages (supports as_of for time-travel "
        "queries). Use rag.get_document to read a document. Use "
        "rag.verify_claim to check whether a statement is supported by the "
        "tenant's documents before you assert it."
    ),
)

_annotations = ToolAnnotations(read_only_hint=True)


async def _tenant_id() -> uuid.UUID:
    """Resolve the tenant from the API key, mirroring api/core/deps.py."""
    import os

    raw = os.environ.get("TRUSTRAG_API_KEY")
    if not raw:
        raise RuntimeError(
            "TRUSTRAG_API_KEY is not set — create a key in the dashboard "
            "or via POST /auth/api-keys."
        )
    async with get_session_factory()() as session:
        key = await session.scalar(
            select(ApiKey).where(
                ApiKey.key_hash == hash_api_key(raw), ApiKey.is_active
            )
        )
        if key is None:
            raise RuntimeError("TRUSTRAG_API_KEY is invalid or revoked")
        return key.tenant_id


@server.tool(
    name="rag.search",
    title="Search documents",
    annotations=_annotations,
)
async def rag_search(
    query: str,
    top_k: int = 5,
    as_of: str | None = None,
) -> dict:
    """Hybrid semantic + keyword search over the tenant's documents.

    Args:
        query: What to look for, phrased as a standalone question.
        top_k: Number of passages to return (1–10).
        as_of: Optional ISO date/datetime for time travel — retrieve only
            knowledge valid at that instant, e.g. "2026-01-01". Omit for
            the current version of every document.

    Returns:
        Passages with document filename, relevance scores, validity window
        (valid_from/valid_to), and whether each is the current version.
    """
    if not 1 <= top_k <= 10:
        raise ValueError("top_k must be between 1 and 10")
    parsed_as_of = None
    if as_of:
        parsed_as_of = dt.datetime.fromisoformat(as_of)
        if not parsed_as_of.tzinfo:
            parsed_as_of = parsed_as_of.replace(tzinfo=dt.UTC)

    tenant_id = await _tenant_id()
    async with get_session_factory()() as session:
        chunks = await hybrid_search(
            session, tenant_id, query, top_k=top_k, as_of=parsed_as_of
        )
    doc_ids = {c.document_id for c in chunks}
    async with get_session_factory()() as session:
        docs = {
            d.id: d.filename
            for d in await session.scalars(
                select(Document).where(Document.id.in_(doc_ids))
            )
        }
    return {
        "query": query,
        "as_of": as_of,
        "passages": [
            {
                "document": docs.get(c.document_id, "unknown"),
                "content": c.content,
                "rrf_score": c.rrf_score,
                "found_by": "dense+bm25" if c.from_both_legs else "dense" if c.dense_rank else "bm25",
                "valid_from": c.valid_from.isoformat() if c.valid_from else None,
                "valid_to": c.valid_to.isoformat() if c.valid_to else None,
                "is_current": c.is_current,
            }
            for c in chunks
        ],
    }


@server.tool(
    name="rag.get_document",
    title="List or read documents",
    annotations=_annotations,
)
async def rag_get_document(
    filename: str | None = None,
    document_id: str | None = None,
) -> dict:
    """List the tenant's documents (with version chains), or read one.

    Call with no arguments to list every document including superseded
    versions. Pass filename or document_id to get one document's metadata
    and full chunk contents.
    """
    tenant_id = await _tenant_id()
    async with get_session_factory()() as session:
        stmt = select(Document).where(Document.tenant_id == tenant_id)
        if document_id:
            stmt = stmt.where(Document.id == uuid.UUID(document_id))
        elif filename:
            stmt = stmt.where(Document.filename == filename)
        docs = list(await session.scalars(stmt.order_by(Document.created_at)))
        if not docs:
            return {"documents": []}
        if document_id or filename:
            doc = docs[-1]  # filename may match several versions; newest wins
            rows = await session.scalars(
                select(Chunk)
                .where(Chunk.document_id == doc.id)
                .order_by(Chunk.chunk_index)
            )
            chunks = [
                {
                    "index": r.chunk_index,
                    "content": r.content,
                    "valid_from": r.valid_from.isoformat() if r.valid_from else None,
                    "valid_to": r.valid_to.isoformat() if r.valid_to else None,
                }
                for r in rows
            ]
            return {
                "document": {
                    "id": str(doc.id),
                    "filename": doc.filename,
                    "status": doc.status,
                    "supersedes_id": str(doc.supersedes_id) if doc.supersedes_id else None,
                    "created_at": doc.created_at.isoformat(),
                },
                "chunks": chunks,
            }
        return {
            "documents": [
                {
                    "id": str(d.id),
                    "filename": d.filename,
                    "status": d.status,
                    "supersedes_id": str(d.supersedes_id) if d.supersedes_id else None,
                    "created_at": d.created_at.isoformat(),
                }
                for d in docs
            ]
        }


@server.tool(
    name="rag.verify_claim",
    title="Verify a claim against documents",
    annotations=_annotations,
)
async def rag_verify_claim(claim: str) -> dict:
    """Check whether a statement is supported by the tenant's documents.

    Retrieves evidence for the claim, extracts it into atomic claims, and
    runs entailment verification: each claim gets a verdict of verified,
    unsupported, or contradicted, plus an overall confidence score
    (abstain below 0.5 means the evidence isn't there — don't assert it).
    """
    tenant_id = await _tenant_id()
    async with get_session_factory()() as session:
        chunks = await hybrid_search(session, tenant_id, claim, top_k=5)
        if not chunks:
            return {
                "claim": claim,
                "verdict": "unsupported",
                "confidence": 0.0,
                "abstain": True,
                "reason": "no passages found for this claim",
                "claims": [],
            }
        verification = await verify_answer(claim, chunks)
    return {
        "claim": claim,
        "verdict": (
            "verified"
            if not verification.abstain
            and all(c.verdict == "verified" for c in verification.claims)
            else "abstain" if verification.abstain else "mixed"
        ),
        "confidence": verification.confidence,
        "abstain": verification.abstain,
        "reason": verification.reason,
        "claims": [
            {"text": c.text, "verdict": c.verdict} for c in verification.claims
        ],
        "evidence_passages": len(chunks),
    }


def main() -> None:
    init_engine(get_settings().database_url)
    server.run(transport="stdio")


if __name__ == "__main__":
    main()
