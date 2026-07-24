"""
Helper to parse PDF and DOCX files.
PDF uses PyMuPDF, DOCX uses python-docx.
"""
from __future__ import annotations

from pathlib import Path

from app.core.exceptions import UnsupportedFileTypeError
from app.models.enums import FileType

# Average paragraphs per page for word files
_DOCX_PARAS_PER_PAGE = 40


def parse_document(path: Path, file_type: FileType) -> tuple[list[tuple[int, str]], int]:
    # Route parsing based on file type
    if file_type is FileType.pdf:
        return _parse_pdf(path)
    if file_type is FileType.docx:
        return _parse_docx(path)
    raise UnsupportedFileTypeError()


def _parse_pdf(path: Path) -> tuple[list[tuple[int, str]], int]:
    import fitz  # PyMuPDF

    pages: list[tuple[int, str]] = []
    with fitz.open(path) as doc:
        for i, page in enumerate(doc, start=1):
            text = page.get_text("text") or ""
            if text.strip():
                pages.append((i, text))
        page_count = doc.page_count
    return pages, page_count


def _parse_docx(path: Path) -> tuple[list[tuple[int, str]], int]:
    import docx

    document = docx.Document(str(path))
    paragraphs = [p.text for p in document.paragraphs if p.text and p.text.strip()]
    
    # Also extract table text so we don't miss data
    for table in document.tables:
        for row in table.rows:
            cells = " | ".join(c.text.strip() for c in row.cells if c.text.strip())
            if cells:
                paragraphs.append(cells)

    pages: list[tuple[int, str]] = []
    for i in range(0, len(paragraphs), _DOCX_PARAS_PER_PAGE):
        page_number = i // _DOCX_PARAS_PER_PAGE + 1
        pages.append((page_number, "\n".join(paragraphs[i : i + _DOCX_PARAS_PER_PAGE])))
    return pages, max(1, len(pages))
