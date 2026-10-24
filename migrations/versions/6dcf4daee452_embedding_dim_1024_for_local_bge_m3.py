"""embedding dim 1024 for local bge-m3

Revision ID: 6dcf4daee452
Revises: d1ad51f5547d
Create Date: 2026-10-24

"""
from collections.abc import Sequence

from alembic import op

revision: str = '6dcf4daee452'
down_revision: str | Sequence[str] | None = 'd1ad51f5547d'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Switch embeddings to local BGE-M3 (1024-dim).

    Previous vectors are dimensionally incompatible — chunks are cleared and
    documents revert to pending for re-ingestion.
    """
    op.execute("DROP INDEX IF EXISTS ix_chunks_embedding_hnsw")
    op.execute("DELETE FROM chunks")
    op.execute("ALTER TABLE chunks ALTER COLUMN embedding TYPE vector(1024)")
    op.execute(
        "CREATE INDEX ix_chunks_embedding_hnsw ON chunks "
        "USING hnsw (embedding vector_cosine_ops) WITH (m = 16, ef_construction = 64)"
    )
    op.execute("UPDATE documents SET status = 'PENDING' WHERE status = 'INDEXED'")


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_chunks_embedding_hnsw")
    op.execute("DELETE FROM chunks")
    op.execute("ALTER TABLE chunks ALTER COLUMN embedding TYPE vector(2000)")
    op.execute(
        "CREATE INDEX ix_chunks_embedding_hnsw ON chunks "
        "USING hnsw (embedding vector_cosine_ops) WITH (m = 16, ef_construction = 64)"
    )
