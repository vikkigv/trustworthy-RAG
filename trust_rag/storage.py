"""File storage abstraction.

Bytes live outside Postgres (large blobs don't belong in the DB). The interface
is deliberately minimal so the local-filesystem backend can be swapped for S3
at deploy time without touching callers.
"""

import hashlib
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

import aiofiles


@dataclass(frozen=True)
class StoredFile:
    path: str  # storage-relative path (object key in S3 terms)
    checksum: str  # sha256 hex
    size: int


class ObjectStorage(Protocol):
    async def save(self, tenant_id: uuid.UUID, document_id: uuid.UUID, data: bytes) -> StoredFile: ...
    async def open(self, path: str) -> bytes: ...
    async def delete(self, path: str) -> None: ...


class LocalStorage:
    """Filesystem backend: <root>/<tenant_id>/<document_id> — original filename
    is intentionally not used as a path component (path traversal safety)."""

    def __init__(self, root: str) -> None:
        self._root = Path(root).resolve()
        self._root.mkdir(parents=True, exist_ok=True)

    async def save(
        self, tenant_id: uuid.UUID, document_id: uuid.UUID, data: bytes
    ) -> StoredFile:
        rel = Path(str(tenant_id)) / str(document_id)
        target = (self._root / rel).resolve()
        if not target.is_relative_to(self._root):
            raise ValueError("path escapes storage root")
        target.parent.mkdir(parents=True, exist_ok=True)
        async with aiofiles.open(target, "wb") as f:
            await f.write(data)
        return StoredFile(
            path=str(rel),
            checksum=hashlib.sha256(data).hexdigest(),
            size=len(data),
        )

    async def open(self, path: str) -> bytes:
        target = (self._root / path).resolve()
        if not target.is_relative_to(self._root):
            raise ValueError("path escapes storage root")
        async with aiofiles.open(target, "rb") as f:
            return await f.read()

    async def delete(self, path: str) -> None:
        target = (self._root / path).resolve()
        if target.is_relative_to(self._root) and target.exists():
            target.unlink()


_storage: ObjectStorage | None = None


def init_storage(root: str) -> ObjectStorage:
    global _storage
    _storage = LocalStorage(root)
    return _storage


def get_storage() -> ObjectStorage:
    assert _storage is not None, "init_storage() must be called first"
    return _storage
