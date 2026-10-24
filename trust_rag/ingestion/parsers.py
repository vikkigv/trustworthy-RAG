"""Document parsers: bytes → plain text, one function per supported MIME type."""

import io
from collections.abc import Callable
from typing import Protocol

Parser = Callable[[bytes], str]


class UnsupportedDocumentType(ValueError):
    pass


def _parse_pdf(data: bytes) -> str:
    from pypdf import PdfReader

    reader = PdfReader(io.BytesIO(data))
    pages = [page.extract_text() or "" for page in reader.pages]
    return "\n\n".join(pages).strip()


def _parse_docx(data: bytes) -> str:
    from docx import Document

    document = Document(io.BytesIO(data))
    return "\n\n".join(p.text for p in document.paragraphs if p.text).strip()


def _parse_text(data: bytes) -> str:
    return data.decode("utf-8", errors="replace").strip()


_PARSERS: dict[str, Parser] = {
    "application/pdf": _parse_pdf,
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document": _parse_docx,
    "text/markdown": _parse_text,
    "text/plain": _parse_text,
}


def get_parser(mime_type: str) -> Parser:
    parser = _PARSERS.get(mime_type)
    if parser is None:
        raise UnsupportedDocumentType(f"No parser for {mime_type!r}")
    return parser


class SupportsMimeType(Protocol):  # for type-checking callers that hand over a Document
    mime_type: str


def parse(data: bytes, mime_type: str) -> str:
    text = get_parser(mime_type)(data)
    if not text:
        raise ValueError("Document produced no extractable text")
    return text
