"""Extract plain text from documents (PDF, text formats, images).

PDF text extraction uses ``pypdf`` when installed; without it PDFs are still
registered but reported as unsupported rather than failing. Images need OCR,
which is intentionally not a dependency — they are registered and flagged.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path

logger = logging.getLogger(__name__)

TEXT_SUFFIXES = {
    ".txt", ".md", ".markdown", ".csv", ".tsv", ".json", ".log", ".yaml", ".yml",
    ".rst", ".org", ".ini", ".cfg",
}
IMAGE_SUFFIXES = {
    ".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp", ".tif", ".tiff", ".heic",
}
PDF_SUFFIXES = {".pdf"}

STATUS_INDEXED = "indexed"
STATUS_UNSUPPORTED = "unsupported"
STATUS_ERROR = "error"
#: Extraction worked but produced nothing usable (scanned PDF, empty file).
#: Distinct from ``indexed`` so it is visible in the UI and gets retried later.
STATUS_EMPTY = "empty"


def has_pdf_support() -> bool:
    """Whether ``pypdf`` is importable in this interpreter."""
    try:
        import pypdf  # noqa: F401
    except ImportError:
        return False
    return True


@dataclass
class Extracted:
    kind: str
    text: str = ""
    pages: int | None = None
    #: Per-page text, when the format has pages (PDF). Used for citations.
    page_texts: list[str] | None = None
    status: str = STATUS_INDEXED
    error: str | None = None


def extract_text(path: Path, *, max_pages: int = 50, max_chars: int = 200_000) -> Extracted:
    """Extract text from a file, with size/page caps and clear failure modes."""
    path = Path(path)
    suffix = path.suffix.lower()
    if suffix in PDF_SUFFIXES:
        return _extract_pdf(path, max_pages=max_pages, max_chars=max_chars)
    if suffix in TEXT_SUFFIXES:
        return _empty_if_blank(_extract_plain(path, max_chars=max_chars))
    if suffix in IMAGE_SUFFIXES:
        return Extracted(
            kind="image", status=STATUS_UNSUPPORTED,
            error="image text extraction requires OCR (not configured)",
        )
    return Extracted(
        kind="other", status=STATUS_UNSUPPORTED,
        error=f"unsupported file type: {suffix or 'unknown'}",
    )


def _extract_plain(path: Path, *, max_chars: int) -> Extracted:
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError as e:
        return Extracted(kind="text", status=STATUS_ERROR, error=str(e))
    return Extracted(kind="text", text=text[:max_chars], pages=None)


def _empty_if_blank(
    extracted: Extracted, *, hint: str = "empty file or scanned image"
) -> Extracted:
    """Flag a successful but empty extraction instead of calling it indexed."""
    if extracted.status == STATUS_INDEXED and not extracted.text.strip():
        extracted.status = STATUS_EMPTY
        extracted.error = f"no extractable text ({hint})"
    return extracted


def _extract_pdf(path: Path, *, max_pages: int, max_chars: int) -> Extracted:
    try:
        from pypdf import PdfReader
    except ImportError:
        return Extracted(
            kind="pdf", status=STATUS_UNSUPPORTED,
            error="PDF support requires the 'pypdf' package (pip install pypdf)",
        )

    try:
        reader = PdfReader(str(path))
        total_pages = len(reader.pages)
        page_texts: list[str] = []
        used = 0
        for index, page in enumerate(reader.pages):
            if index >= max_pages or used >= max_chars:
                break
            try:
                text = page.extract_text() or ""
            except Exception:  # noqa: BLE001 - a single bad page must not abort
                logger.debug("Failed to extract page %s of %s", index, path)
                text = ""
            remaining = max_chars - used
            page_texts.append(text[:remaining])
            used += len(text)
    except Exception as e:  # noqa: BLE001 - malformed PDFs
        return Extracted(kind="pdf", status=STATUS_ERROR, error=str(e))

    return _empty_if_blank(
        Extracted(
            kind="pdf",
            text="\n\n".join(page_texts)[:max_chars],
            pages=total_pages,
            page_texts=page_texts,
        ),
        hint="scanned PDF without a text layer? OCR is not configured",
    )
