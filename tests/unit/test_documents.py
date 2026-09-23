"""Tests for the document knowledge base and document tools (#20, #21)."""

import json
from pathlib import Path

import pytest
from fava_ai.documents.chunking import chunk_pages, chunk_text
from fava_ai.documents.extract import (
    STATUS_ERROR,
    STATUS_INDEXED,
    STATUS_UNSUPPORTED,
    extract_text,
)
from fava_ai.documents.store import DocumentStore, sanitize_filename
from fava_ai.tools.builtin.documents import (
    FileDocumentTool,
    ReadDocumentTool,
    SearchDocumentsTool,
)


def make_pdf(text: str) -> bytes:
    """Build a minimal, valid single-page PDF containing ``text``."""
    objs = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Contents 4 0 R "
        b"/Resources << /Font << /F1 5 0 R >> >> >>",
    ]
    stream = f"BT /F1 18 Tf 72 720 Td ({text}) Tj ET".encode()
    objs.append(b"<< /Length " + str(len(stream)).encode() + b" >>\nstream\n"
                + stream + b"\nendstream")
    objs.append(b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>")
    out = bytearray(b"%PDF-1.4\n")
    offsets = []
    for i, obj in enumerate(objs, 1):
        offsets.append(len(out))
        out += f"{i} 0 obj\n".encode() + obj + b"\nendobj\n"
    xref = len(out)
    out += f"xref\n0 {len(objs)+1}\n".encode() + b"0000000000 65535 f \n"
    for off in offsets:
        out += f"{off:010d} 00000 n \n".encode()
    out += (f"trailer\n<< /Size {len(objs)+1} /Root 1 0 R >>\n"
            f"startxref\n{xref}\n%%EOF\n").encode()
    return bytes(out)


@pytest.fixture
def store(tmp_path):
    s = DocumentStore(tmp_path / "documents.db", tmp_path / "documents")
    s.initialize()
    yield s
    s.close()


@pytest.fixture
def docs_dir(tmp_path):
    d = tmp_path / "docs"
    d.mkdir()
    (d / "lease-2024.md").write_text(
        "# Lease agreement\n\nLandlord: Example Properties\n"
        "Monthly rent: 1500 CAD\nTerm: 2024-01-01 to 2024-12-31\n\n"
        "The tenant shall pay rent on the first of each month."
    )
    (d / "receipt-cafe.txt").write_text(
        "CAFE MILANO\n2024-03-05\nLatte 4.50\nPanini 9.00\nTotal 13.50 CAD"
    )
    (d / "statement.pdf").write_bytes(make_pdf("Credit card statement January dispute"))
    (d / "scan.png").write_bytes(b"\x89PNG\r\n\x1a\n not really an image")
    return d


# ── extraction ────────────────────────────────────────────────────


def test_extract_plain_text(tmp_path):
    path = tmp_path / "a.txt"
    path.write_text("hello world")
    result = extract_text(path)
    assert result.status == STATUS_INDEXED
    assert result.text == "hello world"


def test_extract_pdf(tmp_path):
    path = tmp_path / "a.pdf"
    path.write_bytes(make_pdf("Invoice 1234"))
    result = extract_text(path)
    assert result.status == STATUS_INDEXED
    assert "Invoice 1234" in result.text
    assert result.pages == 1


def test_extract_pdf_is_capped(tmp_path):
    path = tmp_path / "a.pdf"
    path.write_bytes(make_pdf("x" * 5000))
    result = extract_text(path, max_chars=100)
    assert len(result.text) <= 100


def test_extract_malformed_pdf_reports_error(tmp_path):
    path = tmp_path / "broken.pdf"
    path.write_bytes(b"%PDF-1.4 not a real pdf")
    result = extract_text(path)
    assert result.status in (STATUS_ERROR, STATUS_UNSUPPORTED)


def test_extract_image_is_unsupported_without_ocr(tmp_path):
    path = tmp_path / "a.png"
    path.write_bytes(b"\x89PNG\r\n\x1a\n")
    result = extract_text(path)
    assert result.status == STATUS_UNSUPPORTED
    assert "OCR" in (result.error or "")


def test_extract_unknown_type(tmp_path):
    path = tmp_path / "a.zip"
    path.write_bytes(b"PK\x03\x04")
    assert extract_text(path).status == STATUS_UNSUPPORTED


# ── chunking ──────────────────────────────────────────────────────


def test_chunk_text_splits_and_caps():
    text = "\n\n".join(f"paragraph number {i} " + "word " * 40 for i in range(5))
    chunks = chunk_text(text, max_chars=500, overlap=50)
    assert len(chunks) > 1
    assert all(len(c.text) <= 500 + 60 for c in chunks)


def test_chunk_text_hard_splits_long_paragraph():
    chunks = chunk_text("x" * 5000, max_chars=1000, overlap=100)
    assert len(chunks) >= 5
    assert all(len(c.text) <= 1000 for c in chunks)


def test_chunk_pages_keeps_page_numbers():
    chunks = chunk_pages(["page one text", "page two text"], max_chars=100)
    assert [c.page for c in chunks] == [1, 2]


def test_chunk_empty_text():
    assert chunk_text("") == []
    assert chunk_text("   \n\n  ") == []


# ── store ─────────────────────────────────────────────────────────


def test_sanitize_filename_strips_paths():
    assert sanitize_filename("../../etc/passwd") == "passwd"
    assert "/" not in sanitize_filename("a/b/c.pdf")


def test_sanitize_filename_accepts_bytes():
    # Some HTTP clients send a bytes filename; it must not crash.
    assert sanitize_filename(b"from-bytes.txt") == "from-bytes.txt"
    assert sanitize_filename(b"../../evil.pdf") == "evil.pdf"
    assert sanitize_filename("") == "document"


def test_store_indexes_and_searches(store, docs_dir):
    stats = store.scan_folders([docs_dir])
    assert stats["indexed"] == 4
    assert stats["errors"] == 0

    status = store.status()
    assert status["documents"] == 4
    assert status["by_status"].get("indexed") == 3
    assert status["by_status"].get("unsupported") == 1

    hits = store.search("landlord rent")
    assert hits and hits[0]["name"] == "lease-2024.md"
    assert "[" in hits[0]["snippet"]

    hits = store.search("latte panini")
    assert hits and hits[0]["name"] == "receipt-cafe.txt"

    hits = store.search("statement dispute")
    assert any(h["name"] == "statement.pdf" and h["page"] == 1 for h in hits)


def test_store_scan_is_incremental(store, docs_dir):
    store.scan_folders([docs_dir])
    again = store.scan_folders([docs_dir])
    assert again["indexed"] == 0
    assert again["skipped"] == 4


def test_store_dedup_by_content(store, tmp_path):
    a = tmp_path / "a.txt"
    a.write_text("same content")
    b = tmp_path / "b.txt"
    b.write_text("same content")
    first = store.import_path(a)
    second = store.import_path(b)
    assert first["id"] == second["id"]
    assert store.status()["documents"] == 1


def test_store_read_and_delete(store, docs_dir):
    store.scan_folders([docs_dir])
    doc = next(d for d in store.list_documents() if d["name"] == "lease-2024.md")

    read = store.read(doc["id"], max_chars=40)
    assert read["text"].startswith("# Lease agreement")
    assert read["truncated"] is True

    assert store.delete(doc["id"]) is True
    assert store.get(doc["id"]) is None
    assert store.search("landlord") == []


def test_store_empty_search_returns_nothing(store, docs_dir):
    store.scan_folders([docs_dir])
    assert store.search("!!! ???") == []


def test_store_assign_conversation(store, docs_dir):
    store.scan_folders([docs_dir])
    doc = store.list_documents()[0]
    assert doc["conversation_id"] is None
    store.assign_conversation([doc["id"]], "conv-1")
    assert store.get(doc["id"])["conversation_id"] == "conv-1"
    assert [d["id"] for d in store.list_documents(conversation_id="conv-1")] == [doc["id"]]


def test_store_upload_copies_into_documents_dir(store, tmp_path):
    src = tmp_path / "receipt.pdf"
    src.write_bytes(make_pdf("Uploaded receipt"))
    doc = store.import_path(src, conversation_id="c1", dest_dir=store.documents_dir / "c1")
    stored = Path(doc["source_path"])
    assert stored.exists()
    assert stored.parent.name == "c1"
    assert doc["conversation_id"] == "c1"


# ── tools ─────────────────────────────────────────────────────────


def test_search_documents_tool(store, docs_dir):
    store.scan_folders([docs_dir])
    result = SearchDocumentsTool(store).execute(query="rent")
    data = json.loads(result.content)
    assert data["count"] >= 1
    assert data["results"][0]["name"] == "lease-2024.md"


def test_read_document_tool(store, docs_dir):
    store.scan_folders([docs_dir])
    doc = next(d for d in store.list_documents() if d["name"].startswith("lease"))
    data = json.loads(ReadDocumentTool(store).execute(document_id=doc["id"]).content)
    assert "Lease agreement" in data["text"]


def test_read_document_tool_missing(store):
    result = ReadDocumentTool(store).execute(document_id="nope")
    assert result.metadata["error"]


def test_file_document_returns_paste_ready_snippet(store, docs_dir):
    store.scan_folders([docs_dir])
    doc = next(d for d in store.list_documents() if d["name"].startswith("lease"))
    tool = FileDocumentTool(store, ledger_dir=str(Path(doc["source_path"]).parent))
    result = tool.execute(
        document_id=doc["id"], date="2024-03-05", payee="Landlord",
        narration="March rent",
        postings=[
            {"account": "Expenses:Rent", "amount": "1500.00 CAD"},
            {"account": "Assets:Bank:Checking", "amount": "-1500.00 CAD"},
        ],
    )
    assert tool.permission == "readonly"
    snippet = json.loads(result.content)["snippet"]
    assert snippet.startswith("2024-03-05 *")
    assert "attachment:" in snippet
    assert "document Expenses:Rent" in snippet
    assert "1500.00 CAD" in snippet


def test_file_document_opt_in_write(store, docs_dir, tmp_path):
    store.scan_folders([docs_dir])
    doc = next(d for d in store.list_documents() if d["name"].startswith("lease"))
    ledger_dir = tmp_path / "ledger"
    ledger_dir.mkdir()
    tool = FileDocumentTool(
        store, ledger_dir=str(ledger_dir), allow_writes=True,
        writes_file="documents.beancount",
    )
    assert tool.permission == "write"
    result = tool.execute(
        document_id=doc["id"], date="2024-03-05",
        postings=[{"account": "Expenses:Rent", "amount": "1500.00 CAD"}],
    )
    written = Path(json.loads(result.content)["written_to"])
    assert written.name == "documents.beancount"
    assert "attachment:" in written.read_text()


def test_file_document_requires_postings(store, docs_dir):
    store.scan_folders([docs_dir])
    doc = store.list_documents()[0]
    result = FileDocumentTool(store).execute(document_id=doc["id"], date="2024-01-01", postings=[])
    assert result.metadata["error"]


# ── embeddings & hybrid retrieval ─────────────────────────────────

from fava_ai.documents.embeddings import EmbeddingClient, EmbeddingError  # noqa: E402


class _FakeResponse:
    def __init__(self, payload, status=200, text=""):
        self._payload = payload
        self.status_code = status
        self.text = text

    def json(self):
        return self._payload


def _fake_embeddings(monkeypatch, dim=16):
    """Deterministic bag-of-words vectors, so ranking is reproducible."""
    def fake_post(url, json=None, headers=None, timeout=None):
        texts = json["input"]
        if isinstance(texts, str):
            texts = [texts]
        data = []
        for i, text in enumerate(texts):
            vec = [0.0] * dim
            for word in text.lower().split():
                vec[hash(word) % dim] += 1.0
            data.append({"index": i, "embedding": vec})
        return _FakeResponse({"data": data})

    monkeypatch.setattr("fava_ai.documents.embeddings.requests.post", fake_post)


def test_embedding_client_requires_config():
    client = EmbeddingClient()
    assert client.configured is False
    with pytest.raises(EmbeddingError):
        client.embed(["x"])


def test_embedding_client_batches_and_orders(monkeypatch):
    _fake_embeddings(monkeypatch)
    client = EmbeddingClient(base_url="http://x/v1", api_key="k", model="m", batch_size=2)
    vectors = client.embed(["a", "b", "c"])
    assert len(vectors) == 3
    assert len(vectors[0]) == 16


def test_embedding_client_reports_http_error(monkeypatch):
    monkeypatch.setattr(
        "fava_ai.documents.embeddings.requests.post",
        lambda *a, **k: _FakeResponse({}, status=501, text="no embeddings"),
    )
    client = EmbeddingClient(base_url="http://x/v1", model="m")
    with pytest.raises(EmbeddingError, match="501"):
        client.embed(["x"])


def test_embedding_client_rejects_bad_payload(monkeypatch):
    monkeypatch.setattr(
        "fava_ai.documents.embeddings.requests.post",
        lambda *a, **k: _FakeResponse({"data": []}),
    )
    client = EmbeddingClient(base_url="http://x/v1", model="m")
    with pytest.raises(EmbeddingError):
        client.embed(["x"])


def test_embed_pending_and_hybrid_search(store, docs_dir, monkeypatch):
    _fake_embeddings(monkeypatch)
    store.scan_folders([docs_dir])
    assert store.embedding_status()["configured"] is False

    store.set_embedder(EmbeddingClient(base_url="http://x/v1", model="m"))
    result = store.embed_pending()
    assert result["embedded"] > 0 and result["error"] is None

    status = store.embedding_status()
    assert status["configured"] is True
    assert status["embedded_chunks"] == status["total_chunks"]

    # Second pass is a no-op.
    assert store.embed_pending()["embedded"] == 0

    hits = store.search("landlord rent", mode="hybrid")
    assert any(h["name"] == "lease-2024.md" for h in hits)
    assert store.dense_search("rent", limit=3)


def test_search_modes_without_embeddings_degrade_gracefully(store, docs_dir):
    store.scan_folders([docs_dir])
    assert store.embedding_status()["configured"] is False
    assert store.embed_pending()["error"] == "embedding not configured"
    assert store.dense_search("rent") == []
    # BM25 still works.
    assert store.search("landlord", mode="hybrid")


def test_hybrid_fuses_bm25_and_dense(store, docs_dir, monkeypatch):
    _fake_embeddings(monkeypatch)
    store.scan_folders([docs_dir])
    store.set_embedder(EmbeddingClient(base_url="http://x/v1", model="m"))
    store.embed_pending()
    # "cafe" appears literally only in the receipt; dense matching should not
    # push an unrelated document above it.
    names = [h["name"] for h in store.search("cafe latte", limit=3)]
    assert "receipt-cafe.txt" in names
