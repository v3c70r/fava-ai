"""SQLite-backed document store with an FTS5 (BM25) index and optional dense search.

Dependency-free baseline: FTS5 ships with CPython's sqlite3, which is more than
enough at personal-corpus scale. When an OpenAI-compatible embeddings endpoint
is configured, chunks are also embedded and retrieval becomes hybrid
(BM25 + cosine, fused with reciprocal rank fusion).
"""

from __future__ import annotations

import hashlib
import logging
import math
import re
import shutil
import sqlite3
import threading
from array import array
from datetime import datetime, timezone
from pathlib import Path

from fava_ai.documents.chunking import chunk_pages, chunk_text
from fava_ai.documents.embeddings import EmbeddingClient, EmbeddingError
from fava_ai.documents.extract import (
    STATUS_INDEXED,
    extract_text,
)

logger = logging.getLogger(__name__)

#: Bump when the FTS index layout changes, so initialize() can rebuild it.
#: 2 = CJK characters are space-separated in the index (unicode61 cannot
#: segment CJK on its own, which silently broke Chinese/Japanese search).
SCHEMA_VERSION = 2

#: Suffixes the folder scanner will consider (extraction may still decline).
SCAN_SUFFIXES = {
    ".pdf", ".txt", ".md", ".markdown", ".csv", ".tsv", ".json", ".log",
    ".yaml", ".yml", ".rst", ".org", ".ini", ".cfg",
    ".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp", ".tif", ".tiff",
}

_SCHEMA = """
CREATE TABLE IF NOT EXISTS documents (
    id              TEXT PRIMARY KEY,
    name            TEXT NOT NULL,
    source_path     TEXT NOT NULL,
    kind            TEXT,
    size            INTEGER,
    sha256          TEXT NOT NULL,
    pages           INTEGER,
    chars           INTEGER,
    status          TEXT NOT NULL,
    error           TEXT,
    conversation_id TEXT,
    added_at        TEXT NOT NULL,
    updated_at      TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_documents_sha ON documents(sha256);
CREATE INDEX IF NOT EXISTS idx_documents_conv ON documents(conversation_id);

CREATE TABLE IF NOT EXISTS chunks (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    document_id TEXT NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
    ordinal     INTEGER NOT NULL,
    page        INTEGER,
    text        TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_chunks_document ON chunks(document_id);

CREATE VIRTUAL TABLE IF NOT EXISTS chunks_fts USING fts5(
    text,
    document_id UNINDEXED,
    ordinal UNINDEXED,
    page UNINDEXED
);

CREATE TABLE IF NOT EXISTS chunk_vectors (
    chunk_id INTEGER PRIMARY KEY REFERENCES chunks(id) ON DELETE CASCADE,
    model    TEXT NOT NULL,
    dim      INTEGER NOT NULL,
    vector   BLOB NOT NULL
);

CREATE TABLE IF NOT EXISTS meta (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
"""

_WORD_RE = re.compile(r"[^\W_]+", re.UNICODE)

#: Han, Hiragana, Katakana, Hangul and CJK compatibility ideographs. FTS5's
#: unicode61 tokenizer treats a run of these as ONE token, so "记账软件测试"
#: is unsearchable as "记账" unless we split the characters ourselves.
_CJK_CLASS = (
    r"\u3040-\u30ff\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff\uac00-\ud7af"
)
_CJK_RE = re.compile(f"[{_CJK_CLASS}]")
_CJK_RUN_RE = re.compile(f"[{_CJK_CLASS}]+")
#: Splits a query into (CJK run, other) pairs.
_QUERY_SPLIT_RE = re.compile(f"([{_CJK_CLASS}]+)|([^{_CJK_CLASS}]+)")


def _has_cjk(text: str) -> bool:
    return bool(_CJK_RE.search(text))


def segment_cjk(text: str) -> str:
    """Space-separate CJK characters so unicode61 tokenizes each one.

    Applied to indexed text only; stored chunk text stays verbatim.
    """
    if not text or not _CJK_RE.search(text):
        return text
    return _CJK_RUN_RE.sub(lambda m: " " + " ".join(m.group()) + " ", text)


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def sanitize_filename(name: str | bytes) -> str:
    """Strip directory components and unsafe characters from an upload name.

    Accepts bytes because some HTTP clients send a bytes filename.
    """
    if isinstance(name, bytes):
        name = name.decode("utf-8", "replace")
    name = Path(str(name)).name.strip() or "document"
    name = re.sub(r"[^\w.\- ]+", "_", name, flags=re.UNICODE)
    return name[:120] or "document"


def query_terms(query: str) -> list[str]:
    """Terms worth highlighting, in their original form.

    Single-character CJK terms are kept (``记`` is a legitimate query).
    """
    return [
        t.lower() for t in _WORD_RE.findall(query or "")
        if len(t) > 1 or _has_cjk(t)
    ]


def _fts_query(query: str) -> str | None:
    """Build a MATCH expression; CJK runs become a phrase of single chars."""
    parts: list[str] = []
    for cjk_run, other in _QUERY_SPLIT_RE.findall(query or ""):
        if cjk_run:
            # "记账" indexed as "记 账" -> phrase "记 账" keeps precision.
            parts.append('"' + " ".join(cjk_run) + '"')
        elif other:
            parts.extend(
                f'"{word.lower()}"' for word in _WORD_RE.findall(other)
                if len(word) > 1
            )
    if not parts:
        return None
    return " OR ".join(parts[:12])


def _snippet(text: str, terms: list[str], width: int = 160) -> str:
    lowered = text.lower()
    position = -1
    for term in terms:
        found = lowered.find(term)
        if found != -1 and (position == -1 or found < position):
            position = found
    if position == -1:
        return text[:width].replace("\n", " ")
    start = max(0, position - width // 3)
    excerpt = text[start:start + width].replace("\n", " ")
    for term in sorted(terms, key=len, reverse=True):
        excerpt = re.sub(f"({re.escape(term)})", r"[\1]", excerpt, flags=re.IGNORECASE)
    return ("…" if start else "") + excerpt


def _to_blob(vector: list[float]) -> bytes:
    return array("f", vector).tobytes()


def _from_blob(blob: bytes) -> array:
    values = array("f")
    values.frombytes(blob)
    return values


def _normalize(vector: list[float]) -> list[float]:
    norm = math.sqrt(sum(x * x for x in vector)) or 1.0
    return [x / norm for x in vector]


def _rrf_scores(rankings: list[list[int]], k: int = 60) -> dict[int, float]:
    """Reciprocal rank fusion of several ranked id lists."""
    scores: dict[int, float] = {}
    for ranking in rankings:
        for rank, item in enumerate(ranking):
            scores[item] = scores.get(item, 0.0) + 1.0 / (k + rank + 1)
    return scores


def _safe_dir_name(name: str) -> str | None:
    """Return ``name`` if it is a single, safe path component, else None."""
    if not name or name in (".", ".."):
        return None
    if Path(name).name != name or "/" in name or "\\" in name:
        return None
    return name


class DocumentStore:
    def __init__(self, db_path: Path, documents_dir: Path | None = None,
                 embedder: EmbeddingClient | None = None,
                 hybrid_min_score: float = 0.2):
        self.db_path = Path(db_path)
        self.documents_dir = Path(documents_dir) if documents_dir else None
        self._embedder = embedder
        #: Below this best-cosine the dense ranking is treated as noise and
        #: dropped from the fusion: a weak embedder can return a list of
        #: barely-related chunks and drag the hybrid result below plain BM25.
        #: It does not help when a small model is *confidently* wrong (best
        #: cosine well above the floor) - that needs a higher value.
        self.hybrid_min_score = hybrid_min_score
        self._conn: sqlite3.Connection | None = None
        self._lock = threading.Lock()
        self._vector_cache: list[tuple[int, array]] | None = None
        self._vector_cache_model: str | None = None

    # ── connection / schema ───────────────────────────────────────

    @property
    def conn(self) -> sqlite3.Connection:
        if self._conn is None:
            self._conn = sqlite3.connect(str(self.db_path), check_same_thread=False)
            self._conn.row_factory = sqlite3.Row
            self._conn.execute("PRAGMA journal_mode=WAL")
            self._conn.execute("PRAGMA foreign_keys=ON")
        return self._conn

    def initialize(self):
        with self._lock:
            self.conn.executescript(_SCHEMA)
            self._migrate()
            self.conn.commit()

    def _migrate(self):
        row = self.conn.execute(
            "SELECT value FROM meta WHERE key = 'schema_version'"
        ).fetchone()
        current = int(row["value"]) if row and str(row["value"]).isdigit() else 0
        if current < SCHEMA_VERSION:
            # v2 changed how text is tokenized (CJK segmentation), which only
            # affects the index columns, so re-derive them from the raw chunks.
            self._rebuild_fts()
        self.conn.execute(
            "INSERT OR REPLACE INTO meta (key, value) VALUES ('schema_version', ?)",
            (str(SCHEMA_VERSION),),
        )

    def _rebuild_fts(self):
        """Re-populate the FTS index from the stored raw chunk text."""
        self.conn.execute("DELETE FROM chunks_fts")
        rows = self.conn.execute(
            "SELECT id, document_id, ordinal, page, text FROM chunks"
        ).fetchall()
        for row in rows:
            self.conn.execute(
                "INSERT INTO chunks_fts (rowid, text, document_id, ordinal, page) "
                "VALUES (?,?,?,?,?)",
                (row["id"], segment_cjk(row["text"]), row["document_id"],
                 row["ordinal"], row["page"]),
            )
        if rows:
            logger.info("Rebuilt the document index (%s chunks)", len(rows))

    def close(self):
        with self._lock:
            if self._conn is not None:
                self._conn.close()
                self._conn = None

    def set_embedder(self, embedder: EmbeddingClient | None, *,
                     min_score: float | None = None):
        """Install the embedding client and the retrieval threshold with it."""
        self._embedder = embedder
        if min_score is not None:
            try:
                self.hybrid_min_score = min(max(float(min_score), 0.0), 1.0)
            except (TypeError, ValueError):
                logger.warning("Ignoring invalid hybrid_min_score %r", min_score)
        self._vector_cache = None

    @property
    def embedder(self) -> EmbeddingClient | None:
        return self._embedder

    # ── ingest ────────────────────────────────────────────────────

    def import_path(self, path: Path, *, conversation_id: str | None = None,
                    dest_dir: Path | None = None,
                    max_pages: int = 50, max_chars: int = 200_000,
                    reextract_failed: bool = True) -> dict:
        """Extract, chunk and index one file.

        With ``dest_dir`` the file is first copied into the store (used for chat
        uploads); otherwise it is indexed in place (folder scanning).

        ``reextract_failed`` re-runs extraction when an identical file is
        already recorded but is not usable yet (for example a PDF uploaded
        before ``pypdf`` was installed). Folder scans turn this off and leave
        healing to :meth:`retry_failed`, so a scan never re-parses the same
        broken file twice in one run.
        """
        path = Path(path)
        if not path.is_file():
            raise FileNotFoundError(path)

        if dest_dir is not None:
            dest_dir = Path(dest_dir)
            dest_dir.mkdir(parents=True, exist_ok=True)
            target = dest_dir / sanitize_filename(path.name)
            if target.resolve() != path.resolve():
                shutil.copy2(path, target)
            path = target

        sha = sha256_file(path)
        doc_id = sha[:16]
        size = path.stat().st_size

        with self._lock:
            existing = self.conn.execute(
                "SELECT * FROM documents WHERE id = ?", (doc_id,)
            ).fetchone()
            # Only a cleanly indexed document short-circuits. A file recorded as
            # unsupported/error/empty (e.g. uploaded before pypdf was installed)
            # is re-extracted, otherwise the stale status could never recover.
            if (
                existing is not None
                and existing["sha256"] == sha
                and (not reextract_failed
                     or existing["status"] == STATUS_INDEXED)
            ):
                if conversation_id and not existing["conversation_id"]:
                    self.conn.execute(
                        "UPDATE documents SET conversation_id = ? WHERE id = ?",
                        (conversation_id, doc_id),
                    )
                    self.conn.commit()
                return dict(self.conn.execute(
                    "SELECT * FROM documents WHERE id = ?", (doc_id,)
                ).fetchone())

        extracted = extract_text(path, max_pages=max_pages, max_chars=max_chars)
        chunks = []
        if extracted.status == STATUS_INDEXED and extracted.text.strip():
            if extracted.page_texts:
                chunks = chunk_pages(extracted.page_texts)
            else:
                chunks = chunk_text(extracted.text)

        now = _now()
        with self._lock:
            self.conn.execute(
                """INSERT INTO documents
                   (id, name, source_path, kind, size, sha256, pages, chars,
                    status, error, conversation_id, added_at, updated_at)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)
                   ON CONFLICT(id) DO UPDATE SET
                     name=excluded.name, source_path=excluded.source_path,
                     kind=excluded.kind, size=excluded.size, sha256=excluded.sha256,
                     pages=excluded.pages, chars=excluded.chars, status=excluded.status,
                     error=excluded.error,
                     conversation_id=COALESCE(excluded.conversation_id, documents.conversation_id),
                     updated_at=excluded.updated_at""",
                (doc_id, path.name, str(path), extracted.kind, size, sha,
                 extracted.pages, len(extracted.text), extracted.status,
                 extracted.error, conversation_id, now, now),
            )
            self._replace_chunks(doc_id, chunks)
            self.conn.commit()
            row = self.conn.execute(
                "SELECT * FROM documents WHERE id = ?", (doc_id,)
            ).fetchone()
        return dict(row)

    def _replace_chunks(self, doc_id: str, chunks):
        self.conn.execute(
            "DELETE FROM chunks_fts WHERE rowid IN "
            "(SELECT id FROM chunks WHERE document_id = ?)", (doc_id,)
        )
        self.conn.execute("DELETE FROM chunks WHERE document_id = ?", (doc_id,))
        for ordinal, chunk in enumerate(chunks):
            cursor = self.conn.execute(
                "INSERT INTO chunks (document_id, ordinal, page, text) "
                "VALUES (?,?,?,?)",
                (doc_id, ordinal, chunk.page, chunk.text),
            )
            self.conn.execute(
                "INSERT INTO chunks_fts (rowid, text, document_id, ordinal, page) "
                "VALUES (?,?,?,?,?)",
                (cursor.lastrowid, segment_cjk(chunk.text), doc_id, ordinal,
                 chunk.page),
            )
        self._vector_cache = None

    def scan_folders(self, folders, *, max_files: int = 2000) -> dict:
        """Index every supported file under the given folders (incremental)."""
        stats = {"scanned": 0, "indexed": 0, "skipped": 0, "errors": 0}
        seen = 0
        for folder in folders:
            base = Path(folder).expanduser()
            if not base.is_dir():
                continue
            for path in sorted(base.rglob("*")):
                if seen >= max_files:
                    break
                if not path.is_file() or path.suffix.lower() not in SCAN_SUFFIXES:
                    continue
                seen += 1
                stats["scanned"] += 1
                try:
                    before = self.get_by_path(path)
                    doc = self.import_path(path, reextract_failed=False)
                    if before is not None and before["sha256"] == doc["sha256"]:
                        stats["skipped"] += 1
                    else:
                        stats["indexed"] += 1
                except Exception:  # noqa: BLE001 - keep scanning
                    logger.exception("Failed to index %s", path)
                    stats["errors"] += 1
        return stats

    # ── embeddings ────────────────────────────────────────────────

    def _embedder_model(self) -> str | None:
        if self._embedder and self._embedder.configured:
            return self._embedder.model
        return None

    def embed_pending(self, *, max_chunks: int = 2000) -> dict:
        """Embed chunks that have no vector for the currently configured model."""
        embedder = self._embedder
        if embedder is None or not embedder.configured:
            return {"embedded": 0, "skipped": 0, "error": "embedding not configured"}
        model = embedder.model

        rows = self.conn.execute(
            """SELECT c.id AS id, c.text AS text FROM chunks c
               LEFT JOIN chunk_vectors v
                 ON v.chunk_id = c.id AND v.model = ?
               WHERE v.chunk_id IS NULL
               LIMIT ?""",
            (model, max_chunks),
        ).fetchall()
        if not rows:
            return {"embedded": 0, "skipped": 0, "error": None}

        texts = [r["text"] for r in rows]
        try:
            vectors = embedder.embed(texts)
        except EmbeddingError as e:
            logger.warning("Embedding failed: %s", e)
            return {"embedded": 0, "skipped": len(rows), "error": str(e)}

        with self._lock:
            for row, vector in zip(rows, vectors):
                self.conn.execute(
                    "INSERT OR REPLACE INTO chunk_vectors (chunk_id, model, dim, vector) "
                    "VALUES (?,?,?,?)",
                    (row["id"], model, len(vector), _to_blob(_normalize(vector))),
                )
            self.conn.commit()
        self._vector_cache = None
        return {"embedded": len(rows), "skipped": 0, "error": None}

    def _load_vectors(self) -> list[tuple[int, array]]:
        model = self._embedder_model()
        if not model:
            return []
        if self._vector_cache is not None and self._vector_cache_model == model:
            return self._vector_cache
        rows = self.conn.execute(
            "SELECT chunk_id, vector FROM chunk_vectors WHERE model = ?", (model,)
        ).fetchall()
        self._vector_cache = [(r["chunk_id"], _from_blob(r["vector"])) for r in rows]
        self._vector_cache_model = model
        return self._vector_cache

    def dense_search(self, query: str, *, limit: int = 20) -> list[tuple[int, float]]:
        embedder = self._embedder
        if embedder is None or not embedder.configured:
            return []
        vectors = self._load_vectors()
        if not vectors:
            return []
        try:
            query_vector = _normalize(embedder.embed_one(query))
        except EmbeddingError as e:
            logger.warning("Dense search unavailable: %s", e)
            return []
        scored = [
            (chunk_id, sum(a * b for a, b in zip(query_vector, vector)))
            for chunk_id, vector in vectors
            if len(vector) == len(query_vector)
        ]
        scored.sort(key=lambda item: item[1], reverse=True)
        return scored[:limit]

    def embedding_status(self) -> dict:
        model = self._embedder_model()
        total = self.conn.execute("SELECT COUNT(*) AS n FROM chunks").fetchone()["n"]
        embedded = 0
        if model:
            embedded = self.conn.execute(
                "SELECT COUNT(*) AS n FROM chunk_vectors WHERE model = ?", (model,)
            ).fetchone()["n"]
        return {
            "configured": bool(model),
            "model": model,
            "embedded_chunks": embedded,
            "total_chunks": total,
        }

    # ── queries ───────────────────────────────────────────────────

    def get(self, doc_id: str) -> dict | None:
        row = self.conn.execute(
            "SELECT * FROM documents WHERE id = ?", (doc_id,)
        ).fetchone()
        return dict(row) if row else None

    def get_by_path(self, path: Path) -> dict | None:
        row = self.conn.execute(
            "SELECT * FROM documents WHERE source_path = ?", (str(path),)
        ).fetchone()
        return dict(row) if row else None

    def list_documents(self, *, conversation_id: str | None = None,
                       limit: int = 200) -> list[dict]:
        if conversation_id:
            rows = self.conn.execute(
                "SELECT * FROM documents WHERE conversation_id = ? "
                "ORDER BY updated_at DESC LIMIT ?",
                (conversation_id, limit),
            ).fetchall()
        else:
            rows = self.conn.execute(
                "SELECT * FROM documents ORDER BY updated_at DESC LIMIT ?", (limit,)
            ).fetchall()
        return [dict(r) for r in rows]

    def search(self, query: str, *, limit: int = 5, mode: str = "auto",
               conversation_id: str | None = None) -> list[dict]:
        """Search chunks. ``mode`` is ``auto`` (hybrid when embeddings exist),
        ``bm25`` or ``dense``.

        Results carry a ``score`` (higher is better) that is only comparable
        within one mode: BM25-negated for ``bm25``, cosine for ``dense``, the
        reciprocal-rank-fusion score for ``auto``.
        """
        terms = query_terms(query)
        bm25_scores: dict[int, float] = {}
        match = _fts_query(query)
        if match and mode != "dense":
            rows = self.conn.execute(
                """SELECT c.id AS chunk_id, bm25(chunks_fts) AS score
                   FROM chunks_fts JOIN chunks c ON c.id = chunks_fts.rowid
                   WHERE chunks_fts MATCH ?
                   ORDER BY bm25(chunks_fts) LIMIT ?""",
                (match, max(limit * 4, 20)),
            ).fetchall()
            # bm25() is negative and lower is better; flip the sign so that
            # callers can treat "higher score = better" uniformly.
            bm25_scores = {r["chunk_id"]: -float(r["score"]) for r in rows}
        bm25_ids = list(bm25_scores)

        dense_scores: dict[int, float] = {}
        if mode in ("auto", "hybrid", "dense"):
            dense_scores = dict(
                self.dense_search(query, limit=max(limit * 4, 20))
            )
            # Only relevant for fusion: an explicit `dense` request is answered
            # as asked. If the embedder's best match is barely related, its
            # ranking is noise and would push good BM25 hits down.
            if (
                mode in ("auto", "hybrid")
                and dense_scores
                and max(dense_scores.values()) < self.hybrid_min_score
            ):
                logger.debug(
                    "Ignoring dense ranking for %r: best cosine %.3f < %.3f",
                    query, max(dense_scores.values()), self.hybrid_min_score,
                )
                dense_scores = {}
        dense_ids = list(dense_scores)

        if mode == "dense":
            ranked, scores = dense_ids, dense_scores
        elif dense_ids and mode in ("auto", "hybrid"):
            scores = _rrf_scores([bm25_ids, dense_ids])
            ranked = sorted(scores, key=lambda item: scores[item], reverse=True)
        else:
            ranked, scores = bm25_ids, bm25_scores
        return self._hydrate(ranked[:limit], terms, conversation_id, scores)

    def _hydrate(self, chunk_ids, terms, conversation_id,
                 scores: dict[int, float] | None = None) -> list[dict]:
        results = []
        for chunk_id in chunk_ids:
            row = self.conn.execute(
                "SELECT c.ordinal AS ordinal, c.page AS page, c.text AS text, "
                "d.* FROM chunks c JOIN documents d ON d.id = c.document_id "
                "WHERE c.id = ?",
                (chunk_id,),
            ).fetchone()
            if row is None:
                continue
            if conversation_id and row["conversation_id"] not in (conversation_id, None):
                continue
            results.append({
                "document_id": row["id"],
                "name": row["name"],
                "path": row["source_path"],
                "kind": row["kind"],
                "page": row["page"],
                "chunk": row["ordinal"],
                "score": round(scores.get(chunk_id, 0.0), 6) if scores else None,
                "snippet": _snippet(row["text"], terms),
            })
        return results

    def read(self, doc_id: str, *, chunk: int | None = None,
             max_chars: int = 20_000) -> dict | None:
        doc = self.get(doc_id)
        if doc is None:
            return None
        if chunk is not None:
            row = self.conn.execute(
                "SELECT text FROM chunks WHERE document_id = ? AND ordinal = ?",
                (doc_id, chunk),
            ).fetchone()
            return {**doc, "text": row["text"] if row else "",
                    "requested_chunk": chunk}
        rows = self.conn.execute(
            "SELECT text FROM chunks WHERE document_id = ? ORDER BY ordinal",
            (doc_id,),
        ).fetchall()
        text = "\n\n".join(r["text"] for r in rows)
        truncated = len(text) > max_chars
        return {**doc, "text": text[:max_chars], "truncated": truncated,
                "chunk_count": len(rows)}

    def assign_conversation(self, doc_ids, conversation_id: str) -> None:
        """Attach uploaded documents to the conversation created on first send."""
        if not doc_ids or not conversation_id:
            return
        with self._lock:
            for doc_id in doc_ids:
                self.conn.execute(
                    "UPDATE documents SET conversation_id = ? WHERE id = ?",
                    (conversation_id, doc_id),
                )
            self.conn.commit()

    def delete(self, doc_id: str, *, remove_file: bool = False) -> bool:
        doc = self.get(doc_id)
        if doc is None:
            return False
        with self._lock:
            self.conn.execute(
                "DELETE FROM chunks_fts WHERE rowid IN "
                "(SELECT id FROM chunks WHERE document_id = ?)", (doc_id,)
            )
            self.conn.execute("DELETE FROM documents WHERE id = ?", (doc_id,))
            self.conn.commit()
        self._vector_cache = None
        if remove_file:
            try:
                Path(doc["source_path"]).unlink(missing_ok=True)
            except OSError:
                logger.warning("Could not remove %s", doc["source_path"])
        return True

    def retry_failed(self, *, max_docs: int = 200) -> dict:
        """Re-extract documents that failed or produced no usable text.

        Without this, a document recorded as unsupported/empty (for example a
        PDF uploaded before ``pypdf`` was installed) stayed broken forever.
        """
        rows = self.conn.execute(
            "SELECT id, source_path, conversation_id FROM documents "
            "WHERE status != ? ORDER BY updated_at DESC LIMIT ?",
            (STATUS_INDEXED, max_docs),
        ).fetchall()
        retried = indexed = 0
        errors: list[str] = []
        for row in rows:
            path = Path(row["source_path"])
            retried += 1
            if not path.is_file():
                errors.append(f"{path.name}: file is missing")
                continue
            try:
                doc = self.import_path(
                    path, conversation_id=row["conversation_id"]
                )
            except Exception as e:  # noqa: BLE001 - one bad file must not stop the rest
                logger.exception("Re-extraction failed for %s", path)
                errors.append(f"{path.name}: {e}")
                continue
            if doc["status"] == STATUS_INDEXED:
                indexed += 1
            else:
                errors.append(f"{path.name}: {doc['error'] or doc['status']}")
        return {
            "retried": retried,
            "indexed": indexed,
            "still_failed": retried - indexed,
            "errors": errors[:20],
        }

    def delete_conversation(self, conversation_id: str, *,
                            remove_files: bool = True) -> dict:
        """Drop the documents uploaded into a conversation (and their files)."""
        if not conversation_id:
            return {"documents": 0, "removed_dir": None}
        rows = self.conn.execute(
            "SELECT id FROM documents WHERE conversation_id = ?",
            (conversation_id,),
        ).fetchall()
        removed = 0
        for row in rows:
            if self.delete(row["id"], remove_file=remove_files):
                removed += 1

        removed_dir = None
        # Uploads live in <documents_dir>/<conversation_id>/; only touch it when
        # the id is a single safe path component.
        name = _safe_dir_name(conversation_id)
        if remove_files and name and self.documents_dir:
            candidate = self.documents_dir / name
            try:
                if (
                    candidate.is_dir()
                    and candidate.resolve().parent == self.documents_dir.resolve()
                ):
                    shutil.rmtree(candidate, ignore_errors=True)
                    removed_dir = str(candidate)
            except OSError:
                logger.warning("Could not remove %s", candidate)
        return {"documents": removed, "removed_dir": removed_dir}

    def status(self) -> dict:
        total = self.conn.execute("SELECT COUNT(*) AS n FROM documents").fetchone()["n"]
        chunks = self.conn.execute("SELECT COUNT(*) AS n FROM chunks").fetchone()["n"]
        by_status = {
            row["status"]: row["n"]
            for row in self.conn.execute(
                "SELECT status, COUNT(*) AS n FROM documents GROUP BY status"
            ).fetchall()
        }
        return {
            "documents": total,
            "chunks": chunks,
            "by_status": by_status,
            "documents_dir": str(self.documents_dir) if self.documents_dir else None,
            "embedding": self.embedding_status(),
        }
