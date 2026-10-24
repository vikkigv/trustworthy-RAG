"""embedding dim 2000 for zai embedding-3

Revision ID: d1ad51f5547d
Revises: a78cd1c8c4c7
Create Date: 2026-10-24 17:25:54.467282

"""
from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = 'd1ad51f5547d'
down_revision: str | Sequence[str] | None = 'a78cd1c8c4c7'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Switch embeddings from OpenAI 1536-dim to Z.ai embedding-3 2000-dim.

    Existing vectors are dimensionally incompatible, so chunks are cleared —
    documents must be re-ingested (their status reverts to pending).
    """
    op.execute("DROP INDEX IF EXISTS ix_chunks_embedding_hnsw")
    op.execute("DELETE FROM chunks")
    op.execute("ALTER TABLE chunks ALTER COLUMN embedding TYPE vector(2000)")
    op.execute(
        "CREATE INDEX ix_chunks_embedding_hnsw ON chunks "
        "USING hnsw (embedding vector_cosine_ops) WITH (m = 16, ef_construction = 64)"
    )
    op.execute("UPDATE documents SET status = 'PENDING' WHERE status = 'INDEXED'")


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_chunks_embedding_hnsw")
    op.execute("DELETE FROM chunks")
    op.execute("ALTER TABLE chunks ALTER COLUMN embedding TYPE vector(1536)")
    op.execute(
        "CREATE INDEX ix_chunks_embedding_hnsw ON chunks "
        "USING hnsw (embedding vector_cosine_ops) WITH (m = 16, ef_construction = 64)"
    )
