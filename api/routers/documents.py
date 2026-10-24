import hashlib
from typing import Annotated
from uuid import UUID

from arq.connections import ArqRedis
from fastapi import APIRouter, Depends, HTTPException, Request, UploadFile, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from api.core.deps import CurrentAuth, DbSession
from api.schemas.documents import DocumentDetailResponse, DocumentResponse
from trust_rag.db.models import Chunk, Document, DocumentStatus, IngestionJob, IngestionJobStatus
from trust_rag.settings import get_settings
from trust_rag.storage import get_storage

router = APIRouter(prefix="/documents", tags=["documents"])


def get_arq(request: Request) -> ArqRedis:
    return request.app.state.arq


ArqDep = Annotated[ArqRedis, Depends(get_arq)]


async def _get_tenant_document(
    document_id: UUID, tenant_id: UUID, session: AsyncSession
) -> Document:
    result = await session.execute(
        select(Document).where(Document.id == document_id, Document.tenant_id == tenant_id)
    )
    document = result.scalar_one_or_none()
    if document is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Document not found")
    return document


@router.post("", response_model=DocumentResponse, status_code=status.HTTP_201_CREATED)
async def upload_document(
    file: UploadFile,
    ctx: CurrentAuth,
    session: DbSession,
    arq: ArqDep,
) -> Document:
    """Upload a document and enqueue it for ingestion (parse → chunk → embed → index)."""
    settings = get_settings()

    if file.content_type not in settings.allowed_mime_types:
        raise HTTPException(
            status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
            detail=(
                f"Unsupported type {file.content_type!r}; "
                f"allowed: {list(settings.allowed_mime_types)}"
            ),
        )

    data = await file.read()
    if not data:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail="Empty file")
    if len(data) > settings.max_upload_mb * 1024 * 1024:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail=f"File exceeds {settings.max_upload_mb} MB limit",
        )

    checksum = hashlib.sha256(data).hexdigest()
    dup = await session.execute(
        select(Document.id).where(
            Document.tenant_id == ctx.tenant_id, Document.checksum == checksum
        )
    )
    if dup.scalar_one_or_none() is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail="Identical document already uploaded"
        )

    document = Document(
        tenant_id=ctx.tenant_id,
        filename=file.filename or "untitled",
        mime_type=file.content_type or "application/octet-stream",
        checksum=checksum,
        status=DocumentStatus.PENDING,
    )
    session.add(document)
    await session.flush()  # document.id must exist before bytes are stored

    stored = await get_storage().save(ctx.tenant_id, document.id, data)
    assert stored.checksum == checksum  # same bytes, computed twice by design

    session.add(IngestionJob(document_id=document.id, status=IngestionJobStatus.QUEUED))
    await session.commit()
    await arq.enqueue_job("ingest_document", str(document.id))

    await session.refresh(document)
    return document


@router.get("", response_model=list[DocumentResponse])
async def list_documents(ctx: CurrentAuth, session: DbSession) -> list[Document]:
    result = await session.execute(
        select(Document)
        .where(Document.tenant_id == ctx.tenant_id)
        .order_by(Document.created_at.desc())
    )
    return list(result.scalars())


@router.get("/{document_id}", response_model=DocumentDetailResponse)
async def get_document(document_id: UUID, ctx: CurrentAuth, session: DbSession) -> dict[str, object]:
    document = await _get_tenant_document(document_id, ctx.tenant_id, session)

    chunk_count = await session.execute(
        select(func.count()).select_from(Chunk).where(Chunk.document_id == document.id)
    )
    last_error = await session.execute(
        select(IngestionJob.error)
        .where(
            IngestionJob.document_id == document.id,
            IngestionJob.status == IngestionJobStatus.FAILED,
        )
        .order_by(IngestionJob.created_at.desc())
        .limit(1)
    )
    return {
        **{c.name: getattr(document, c.name) for c in Document.__table__.columns},
        "chunk_count": chunk_count.scalar_one(),
        "last_ingestion_error": last_error.scalar_one_or_none(),
    }


@router.delete("/{document_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_document(document_id: UUID, ctx: CurrentAuth, session: DbSession) -> None:
    document = await _get_tenant_document(document_id, ctx.tenant_id, session)

    # Bytes first (best effort), then the row (cascades to chunks + jobs).
    await get_storage().delete(f"{ctx.tenant_id}/{document.id}")
    await session.delete(document)
    await session.commit()
