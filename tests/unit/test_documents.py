"""Tests for the document knowledge base and document tools (#20, #21)."""

import json
from pathlib import Path

import pytest
from fava_ai.documents.chunking import chunk_pages, chunk_text
from fava_ai.documents.extract import (
    STATUS_EMPTY,
    STATUS_ERROR,
    STATUS_INDEXED,
    STATUS_UNSUPPORTED,
    Extracted,
    extract_text,
    has_pdf_support,
)
from fava_ai.documents.store import (
    DocumentStore,
    _fts_query,
    query_terms,
    sanitize_filename,
    segment_cjk,
)
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


# ── review fixes: filing safety ───────────────────────────────────


def test_file_document_refuses_to_write_to_main_ledger(store, docs_dir, tmp_path):
    store.scan_folders([docs_dir])
    doc = next(d for d in store.list_documents() if d["name"].startswith("lease"))
    main_ledger = tmp_path / "main.beancount"
    main_ledger.write_text("")

    tool = FileDocumentTool(
        store, ledger_dir=str(tmp_path), allow_writes=True,
        writes_file="main.beancount",  # misconfiguration: points at the journal
        main_ledger_path=str(main_ledger),
    )
    result = tool.execute(
        document_id=doc["id"], date="2024-03-05",
        postings=[{"account": "Expenses:Rent", "amount": "1.00 CAD"}],
    )
    payload = json.loads(result.content)
    assert payload["write_error"]
    assert "main ledger" in payload["write_error"]
    assert "written_to" not in payload
    assert main_ledger.read_text() == ""  # untouched


def test_file_document_write_failure_is_surfaced(store, docs_dir, tmp_path):
    store.scan_folders([docs_dir])
    doc = store.list_documents()[0]
    tool = FileDocumentTool(
        store, ledger_dir=str(tmp_path / "missing-dir"), allow_writes=True,
        writes_file="documents.beancount",
    )
    result = tool.execute(
        document_id=doc["id"], date="2024-03-05",
        postings=[{"account": "Expenses:Rent", "amount": "1.00 CAD"}],
    )
    payload = json.loads(result.content)
    assert payload["write_error"]
    assert "written_to" not in payload
    assert tool.permission == "write"


def test_file_document_writes_file_name_only(store, docs_dir, tmp_path):
    """A path in ledger_writes_file must not escape the ledger directory."""
    store.scan_folders([docs_dir])
    doc = store.list_documents()[0]
    escape_dir = tmp_path / "escape"
    escape_dir.mkdir()
    (escape_dir / "notes.beancount").write_text("")

    tool = FileDocumentTool(
        store, ledger_dir=str(tmp_path), allow_writes=True,
        writes_file="escape/notes.beancount",
    )
    result = tool.execute(
        document_id=doc["id"], date="2024-03-05",
        postings=[{"account": "Expenses:Rent", "amount": "1.00 CAD"}],
    )
    written = Path(json.loads(result.content)["written_to"])
    assert written.parent == tmp_path          # flattened into the ledger dir
    assert written.name == "notes.beancount"


def test_read_document_coerces_string_chunk(store, docs_dir):
    store.scan_folders([docs_dir])
    doc = next(d for d in store.list_documents() if d["name"].startswith("lease"))
    tool = ReadDocumentTool(store)
    as_string = json.loads(tool.execute(document_id=doc["id"], chunk="0").content)
    as_int = json.loads(tool.execute(document_id=doc["id"], chunk=0).content)
    assert as_string["text"] == as_int["text"]
    assert as_string["text"]


# ── CJK / tokenization (review finding 2.3) ───────────────────────


def test_segment_cjk_splits_only_cjk_runs():
    assert segment_cjk("记账软件测试") == " 记 账 软 件 测 试 "
    # Latin words stay whole, mixed text keeps both searchable.
    assert "CAFE" in segment_cjk("CAFE 记账") and "记 账" in segment_cjk("CAFE 记账")
    assert segment_cjk("plain english") == "plain english"
    assert segment_cjk("") == ""


def test_query_terms_keep_single_character_cjk():
    # `记` is a legitimate one-character query; latin single chars are noise.
    assert query_terms("记") == ["记"]
    assert query_terms("a") == []
    assert query_terms("记账 receipt") == ["记账", "receipt"]
    # Punctuation only -> nothing searchable.
    assert query_terms("***") == []
    assert _fts_query("***") is None


def test_fts_query_uses_a_phrase_for_cjk_runs():
    # A CJK run becomes a single-char phrase so precision is kept.
    assert _fts_query("记账") == '"记 账"'
    assert _fts_query("记账 receipt") == '"记 账" OR "receipt"'


def test_search_finds_unspaced_chinese(store, tmp_path):
    """unicode61 cannot segment CJK, so `记账` used to return nothing."""
    path = tmp_path / "ledger-notes.txt"
    path.write_text("记账软件测试记录：本月支出与收入明细")
    store.import_path(path)

    for query in ("记账", "支出", "记"):
        hits = store.search(query, mode="bm25")
        assert hits, f"no hit for {query!r}"

    hit = store.search("记账", mode="bm25")[0]
    # The snippet must show the raw text, not the spaced index copy.
    assert "记账" in hit["snippet"]
    assert "记 账" not in hit["snippet"]


# ── extraction status & self-healing (review finding 1.3) ─────────


def test_empty_file_is_flagged_not_indexed(tmp_path):
    path = tmp_path / "empty.txt"
    path.write_text("")
    assert extract_text(path).status == STATUS_EMPTY


def test_pdf_without_text_layer_is_flagged(tmp_path):
    path = tmp_path / "scan.pdf"
    path.write_bytes(make_pdf(""))
    result = extract_text(path)
    assert result.status == STATUS_EMPTY
    assert "scanned" in (result.error or "").lower()


def test_has_pdf_support_matches_the_environment():
    import importlib.util

    assert has_pdf_support() is (
        importlib.util.find_spec("pypdf") is not None
    )


def test_failed_extraction_is_retried_on_reimport(store, tmp_path, monkeypatch):
    """A doc that failed once must recover once the extractor works again."""
    from fava_ai.documents import store as store_module

    path = tmp_path / "invoice.pdf"
    path.write_bytes(make_pdf("Invoice 42"))

    real = store_module.extract_text
    monkeypatch.setattr(
        store_module, "extract_text",
        lambda *a, **k: Extracted(
            kind="pdf", status=STATUS_UNSUPPORTED, error="no pypdf"
        ),
    )
    first = store.import_path(path)
    assert first["status"] == STATUS_UNSUPPORTED
    assert store.search("Invoice", mode="bm25") == []

    # Re-importing the identical file must re-extract, not return the cache.
    monkeypatch.setattr(store_module, "extract_text", real)
    second = store.import_path(path)
    assert second["status"] == STATUS_INDEXED
    assert store.search("Invoice", mode="bm25")


def test_scan_folders_does_not_reextract_failures(store, docs_dir):
    """Scans skip unchanged files; healing is retry_failed's job."""
    first = store.scan_folders([docs_dir])
    assert first["scanned"] == 4
    again = store.scan_folders([docs_dir])
    assert again["indexed"] == 0
    assert again["skipped"] == first["scanned"]


def test_retry_failed_recovers_documents(store, tmp_path, monkeypatch):
    from fava_ai.documents import store as store_module

    path = tmp_path / "statement.pdf"
    path.write_bytes(make_pdf("Statement closing balance"))

    real = store_module.extract_text
    monkeypatch.setattr(
        store_module, "extract_text",
        lambda *a, **k: Extracted(
            kind="pdf", status=STATUS_UNSUPPORTED, error="no pypdf"
        ),
    )
    doc = store.import_path(path)
    assert doc["status"] == STATUS_UNSUPPORTED

    # A retry while the extractor is still broken changes nothing.
    retry = store.retry_failed()
    assert retry["retried"] == 1 and retry["indexed"] == 0
    assert retry["still_failed"] == 1 and retry["errors"]

    monkeypatch.setattr(store_module, "extract_text", real)
    retry = store.retry_failed()
    assert retry["retried"] == 1 and retry["indexed"] == 1
    assert retry["still_failed"] == 0
    assert store.search("closing balance", mode="bm25")


def test_retry_failed_skips_deleted_files(store, tmp_path):
    path = tmp_path / "gone.pdf"
    path.write_bytes(make_pdf("temporary"))
    store.import_path(path)
    path.unlink()
    retry = store.retry_failed()
    assert retry["retried"] == 0  # nothing failed, so nothing to retry


# ── lifecycle (#2.2) ──────────────────────────────────────────────


def test_delete_conversation_removes_rows_and_files(store, tmp_path):
    conv = "conv-cleanup"
    uploads = store.documents_dir / conv  # the upload convention
    for name in ("a.txt", "b.txt"):
        source = tmp_path / name
        source.write_text(f"content of {name}")
        store.import_path(source, conversation_id=conv, dest_dir=uploads)

    assert sorted(p.name for p in uploads.iterdir()) == ["a.txt", "b.txt"]
    assert len(store.list_documents(conversation_id=conv)) == 2

    result = store.delete_conversation(conv)
    assert result["documents"] == 2
    assert store.list_documents(conversation_id=conv) == []
    # The upload directory is named after the conversation id.
    assert not uploads.exists()
    assert store.search("content", mode="bm25") == []


def test_delete_conversation_keeps_other_conversations(store, tmp_path):
    for conv in ("keep", "drop"):
        source = tmp_path / f"{conv}.txt"
        source.write_text(f"unique-{conv}")
        store.import_path(
            source, conversation_id=conv, dest_dir=store.documents_dir / conv
        )

    store.delete_conversation("drop")
    remaining = store.list_documents()
    assert [d["conversation_id"] for d in remaining] == ["keep"]


def test_delete_conversation_ignores_unsafe_ids(store, tmp_path):
    store.documents_dir.mkdir(parents=True, exist_ok=True)
    victim = tmp_path / "victim"
    victim.mkdir()
    (victim / "important.txt").write_text("do not delete me")
    # A traversal-looking id must never remove an unrelated directory.
    store.delete_conversation("../victim")
    assert (victim / "important.txt").exists()


# ── index migration (CJK) ─────────────────────────────────────────


def test_index_migration_reesegments_existing_chunks(tmp_path):
    db = tmp_path / "documents.db"
    source = tmp_path / "notes.txt"
    source.write_text("记账软件测试记录")

    first = DocumentStore(db, tmp_path / "documents")
    first.initialize()
    first.import_path(source)
    # Simulate an index written by the previous version (no CJK splitting).
    first.conn.execute("UPDATE chunks_fts SET text = ?", ("记账软件测试记录",))
    first.conn.execute("UPDATE meta SET value = '1' WHERE key = 'schema_version'")
    first.conn.commit()
    assert first.search("记账", mode="bm25") == []  # the reported bug
    first.close()

    reopened = DocumentStore(db, tmp_path / "documents")
    reopened.initialize()  # must migrate the index in place
    assert reopened.search("记账", mode="bm25")
    version = reopened.conn.execute(
        "SELECT value FROM meta WHERE key = 'schema_version'"
    ).fetchone()["value"]
    assert version == "2"
    reopened.close()


def test_initialize_is_idempotent(store, docs_dir):
    store.scan_folders([docs_dir])
    before = len(store.search("rent", mode="bm25"))
    store.initialize()  # must not duplicate or drop index rows
    assert len(store.search("rent", mode="bm25")) == before


# ── relevance scores (#2.4) ───────────────────────────────────────


def test_search_results_carry_a_score(store, docs_dir):
    store.scan_folders([docs_dir])
    hits = store.search("rent", mode="bm25")
    assert hits
    assert all(isinstance(h["score"], float) for h in hits)
    scores = [h["score"] for h in hits]
    assert scores == sorted(scores, reverse=True)


def test_punctuation_only_query_is_reported(store, docs_dir):
    store.scan_folders([docs_dir])
    result = SearchDocumentsTool(store).execute(query="***")
    payload = json.loads(result.content)
    assert payload["results"] == []
    assert "no searchable words" in payload["message"]
