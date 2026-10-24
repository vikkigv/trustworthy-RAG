"""TrustRAG data model.

Tenant isolation: every tenant-owned row carries tenant_id, and every query
path must filter on it at the SQL level (never post-filtered in Python).
"""

import enum
import uuid
from datetime import datetime
from typing import Any

from pgvector.sqlalchemy import Vector
from sqlalchemy import (
    BigInteger,
    DateTime,
    Enum,
    ForeignKey,
    Index,
    Integer,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB, TSVECTOR
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from trust_rag.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin

EMBEDDING_DIM = 1536  # OpenAI text-embedding-3-small


# --- Enumerations (kept DB-backed for integrity + reporting) ---


class DocumentStatus(str, enum.Enum):
    PENDING = "pending"
    PROCESSING = "processing"
    INDEXED = "indexed"
    FAILED = "failed"


class IngestionJobStatus(str, enum.Enum):
    QUEUED = "queued"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"


class ClaimVerdict(str, enum.Enum):
    VERIFIED = "verified"
    UNSUPPORTED = "unsupported"
    CONTRADICTED = "contradicted"


# --- Identity & tenancy ---


class Tenant(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "tenants"

    name: Mapped[str] = mapped_column(Text, nullable=False, unique=True)

    users: Mapped[list["User"]] = relationship(back_populates="tenant")


class User(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "users"

    tenant_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False
    )
    email: Mapped[str] = mapped_column(Text, nullable=False, unique=True)
    hashed_password: Mapped[str] = mapped_column(Text, nullable=False)
    is_active: Mapped[bool] = mapped_column(default=True, nullable=False)

    tenant: Mapped[Tenant] = relationship(back_populates="users")


class ApiKey(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "api_keys"

    tenant_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False
    )
    # Only the SHA-256 hash is stored; the raw key is shown once at creation.
    key_hash: Mapped[str] = mapped_column(Text, nullable=False, unique=True)
    key_prefix: Mapped[str] = mapped_column(Text, nullable=False)  # for UI display
    name: Mapped[str] = mapped_column(Text, nullable=False)
    is_active: Mapped[bool] = mapped_column(default=True, nullable=False)

    __table_args__ = (Index("ix_api_keys_tenant", "tenant_id"),)


# --- Documents & chunks ---


class Document(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "documents"

    tenant_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False
    )
    filename: Mapped[str] = mapped_column(Text, nullable=False)
    mime_type: Mapped[str] = mapped_column(Text, nullable=False)
    checksum: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[DocumentStatus] = mapped_column(
        Enum(DocumentStatus, name="document_status"), default=DocumentStatus.PENDING,
        nullable=False,
    )
    # Later versions of the same logical document link here (temporal RAG, v2.5).
    supersedes_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("documents.id", ondelete="SET NULL"), nullable=True
    )

    chunks: Mapped[list["Chunk"]] = relationship(
        back_populates="document", cascade="all, delete-orphan"
    )

    __table_args__ = (
        Index("ix_documents_tenant_status", "tenant_id", "status"),
        UniqueConstraint("tenant_id", "checksum", name="uq_documents_tenant_checksum"),
    )


class Chunk(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "chunks"

    document_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("documents.id", ondelete="CASCADE"), nullable=False
    )
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), nullable=False  # denormalized for SQL-level tenant filters
    )
    chunk_index: Mapped[int] = mapped_column(Integer, nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    embedding: Mapped[list[float] | None] = mapped_column(
        Vector(EMBEDDING_DIM), nullable=True  # null until the embedder runs
    )
    tsv: Mapped[Any] = mapped_column(TSVECTOR, nullable=True)  # maintained by trigger/job
    metadata_: Mapped[dict[str, Any]] = mapped_column(
        "metadata", JSONB, default=dict, nullable=False
    )
    # Temporal validity window (v2.5); open interval until superseded.
    valid_from: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    valid_to: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    document: Mapped[Document] = relationship(back_populates="chunks")

    __table_args__ = (
        UniqueConstraint("document_id", "chunk_index", name="uq_chunks_document_index"),
        Index("ix_chunks_tenant_validity", "tenant_id", "valid_from", "valid_to"),
        # HNSW (vector) and GIN (tsvector) indexes are created in the initial
        # migration via op.execute — not expressible in declarative DDL.
    )


# --- Query logging & verification ---


class QueryLog(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "query_logs"

    tenant_id: Mapped[uuid.UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    user_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    question: Mapped[str] = mapped_column(Text, nullable=False)
    answer: Mapped[str] = mapped_column(Text, nullable=False, default="")
    confidence: Mapped[float] = mapped_column(nullable=False, default=0.0)
    latency_ms: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    retrieved_chunk_ids: Mapped[list[dict[str, Any]]] = mapped_column(
        JSONB, default=list, nullable=False
    )
    tokens_in: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    tokens_out: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    cost_usd: Mapped[float] = mapped_column(nullable=False, default=0.0)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    claims: Mapped[list["Claim"]] = relationship(
        back_populates="query_log", cascade="all, delete-orphan"
    )

    __table_args__ = (Index("ix_query_logs_tenant_created", "tenant_id", "created_at"),)


class Claim(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "claims"

    query_log_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("query_logs.id", ondelete="CASCADE"), nullable=False
    )
    text: Mapped[str] = mapped_column(Text, nullable=False)
    verdict: Mapped[ClaimVerdict] = mapped_column(
        Enum(ClaimVerdict, name="claim_verdict"), nullable=False
    )
    supporting_chunk_ids: Mapped[list[dict[str, Any]]] = mapped_column(
        JSONB, default=list, nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    query_log: Mapped[QueryLog] = relationship(back_populates="claims")


# --- Evaluation (v1 step 10) ---


class EvalRun(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "eval_runs"

    git_sha: Mapped[str] = mapped_column(Text, nullable=False)
    config: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    scores: Mapped[list["EvalScore"]] = relationship(
        back_populates="eval_run", cascade="all, delete-orphan"
    )


class EvalScore(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "eval_scores"

    eval_run_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("eval_runs.id", ondelete="CASCADE"), nullable=False
    )
    metric: Mapped[str] = mapped_column(Text, nullable=False)  # faithfulness, recall, ...
    value: Mapped[float] = mapped_column(nullable=False)

    eval_run: Mapped[EvalRun] = relationship(back_populates="scores")


# --- Ingestion jobs ---


class IngestionJob(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "ingestion_jobs"

    document_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("documents.id", ondelete="CASCADE"), nullable=False
    )
    status: Mapped[IngestionJobStatus] = mapped_column(
        Enum(IngestionJobStatus, name="ingestion_job_status"),
        default=IngestionJobStatus.QUEUED,
        nullable=False,
    )
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    attempts: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
