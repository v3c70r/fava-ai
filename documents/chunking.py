"""Split extracted document text into indexable chunks."""

from __future__ import annotations

from dataclasses import dataclass

DEFAULT_MAX_CHARS = 1500
DEFAULT_OVERLAP = 150
#: Chunks shorter than this are merged into the previous one.
_MIN_CHUNK = 200


@dataclass
class Chunk:
    text: str
    page: int | None = None


def _paragraphs(text: str) -> list[str]:
    parts = [p.strip() for p in text.replace("\r\n", "\n").split("\n\n")]
    return [p for p in parts if p]


def chunk_text(
    text: str,
    *,
    max_chars: int = DEFAULT_MAX_CHARS,
    overlap: int = DEFAULT_OVERLAP,
) -> list[Chunk]:
    """Pack paragraphs into chunks of at most ``max_chars`` with a little overlap.

    Paragraph (blank-line) boundaries are preferred so a chunk stays coherent.
    """
    text = (text or "").strip()
    if not text:
        return []

    chunks: list[Chunk] = []
    buf = ""
    for para in _paragraphs(text):
        # A single oversized paragraph is hard-split.
        while len(para) > max_chars:
            if buf:
                chunks.append(Chunk(buf))
                buf = ""
            chunks.append(Chunk(para[:max_chars]))
            para = para[max_chars - overlap:]
        if not buf:
            buf = para
        elif len(buf) + len(para) + 2 <= max_chars:
            buf = f"{buf}\n\n{para}"
        else:
            chunks.append(Chunk(buf))
            tail = buf[-overlap:] if overlap else ""
            buf = f"{tail}\n\n{para}" if tail else para

    if buf:
        if chunks and len(buf) < _MIN_CHUNK:
            chunks[-1] = Chunk(f"{chunks[-1].text}\n\n{buf}")
        else:
            chunks.append(Chunk(buf))
    return chunks


def chunk_pages(
    page_texts: list[str],
    *,
    max_chars: int = DEFAULT_MAX_CHARS,
    overlap: int = DEFAULT_OVERLAP,
) -> list[Chunk]:
    """Chunk per page so chunks keep a page number for citation."""
    chunks: list[Chunk] = []
    for number, text in enumerate(page_texts, start=1):
        for chunk in chunk_text(text, max_chars=max_chars, overlap=overlap):
            chunks.append(Chunk(chunk.text, page=number))
    return chunks
