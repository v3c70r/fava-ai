"""Endpoint tests for document upload, indexing, search and chat attachments."""

import io
import json

import yaml

from tests.integration.conftest import StubRuntime, make_result


def _upload(client, name="receipt.txt", content=b"CAFE MILANO\n2024-03-05\nTotal 13.50 CAD",
            conversation_id=None):
    data = {"file": (io.BytesIO(content), name)}
    if conversation_id:
        data["conversation_id"] = conversation_id
    return client.post(
        "/documents_upload", data=data, content_type="multipart/form-data"
    )


def test_upload_get_list_delete(client, ext):
    resp = _upload(client, "receipt.txt")
    assert resp.status_code == 201
    doc = resp.get_json()
    assert doc["name"] == "receipt.txt"
    assert doc["status"] == "indexed"
    assert doc["chars"] > 0
    doc_id = doc["id"]

    fetched = client.get(f"/documents?id={doc_id}").get_json()
    assert "CAFE MILANO" in fetched["text"]

    listed = client.get("/documents?all=1").get_json()
    assert [d["id"] for d in listed] == [doc_id]

    assert client.delete(f"/documents?id={doc_id}").status_code == 200
    assert client.get(f"/documents?id={doc_id}").status_code == 404


def test_upload_requires_file(client, ext):
    resp = client.post("/documents_upload", data={}, content_type="multipart/form-data")
    assert resp.status_code == 400


def test_documents_status(client, ext):
    status = client.get("/documents").get_json()
    assert set(status) >= {"documents", "chunks", "by_status", "embedding", "folders"}
    assert status["embedding"]["configured"] is False


def test_index_without_folders_returns_400(client, ext):
    resp = client.post("/documents_index", json={})
    assert resp.status_code == 400
    assert "folders" in resp.get_json()["error"].lower()


def test_index_configured_folders(client, ext, tmp_path):
    docs_dir = tmp_path / "vault"
    docs_dir.mkdir()
    (docs_dir / "lease.md").write_text(
        "# Lease agreement\nLandlord: Example Properties\nMonthly rent 1500 CAD"
    )
    (docs_dir / "note.txt").write_text("random note")

    (ext.config_dir / "config.yaml").write_text(yaml.dump({
        "documents": {"enabled": True, "folders": [str(docs_dir)]},
    }))
    ext._config_manager._load_yaml()

    resp = client.post("/documents_index", json={})
    assert resp.status_code == 200
    stats = resp.get_json()
    assert stats["indexed"] == 2
    assert stats["status"]["documents"] == 2

    hits = client.get("/documents?all=1").get_json()
    assert {d["name"] for d in hits} == {"lease.md", "note.txt"}


def test_embed_endpoints_report_unconfigured(client, ext):
    resp = client.post("/documents_embed", json={})
    assert resp.status_code == 400
    assert client.post("/documents_embed_test", json={}).get_json()["connected"] is False


def test_config_masks_embedding_api_key(client, ext, tmp_path):
    (ext.config_dir / "config.yaml").write_text(yaml.dump({
        "documents": {
            "enabled": True,
            "embedding": {"base_url": "http://x/v1", "api_key": "secret", "model": "m"},
        }
    }))
    ext._config_manager._load_yaml()

    config = client.get("/config").get_json()
    assert config["documents"]["embedding"]["api_key"] == "***"


def test_chat_passes_attachment_context_and_associates(client, ext):
    doc = _upload(client, "invoice.txt", b"Invoice 1234 from Example Corp").get_json()

    stub = StubRuntime(make_result(conversation_id="conv-docs"))
    ext._agent_runtime = stub

    resp = client.post("/chat", json={
        "message": "What is on this invoice?",
        "file_ids": [doc["id"]],
    })
    assert resp.status_code == 200

    extra = stub.calls[-1].get("extra_context", "")
    assert "invoice.txt" in extra
    assert "Invoice 1234" in extra  # small document is inlined

    # The upload is now tied to the conversation so follow-ups can see it.
    conv_docs = client.get("/documents?conversation_id=conv-docs").get_json()
    assert [d["id"] for d in conv_docs] == [doc["id"]]


def test_chat_without_attachments_has_no_extra_context(client, ext):
    stub = StubRuntime(make_result())
    ext._agent_runtime = stub
    client.post("/chat", json={"message": "hello"})
    assert not stub.calls[-1].get("extra_context")


def test_attachment_context_follows_conversation(client, ext):
    """A follow-up without file_ids still sees the conversation's documents."""
    doc = _upload(
        client, "statement.txt", b"Credit card statement", conversation_id="conv-1"
    ).get_json()

    stub = StubRuntime(make_result(conversation_id="conv-1"))
    ext._agent_runtime = stub
    client.post("/chat", json={"message": "and the total?", "conversation_id": "conv-1"})

    extra = stub.calls[-1].get("extra_context", "")
    assert "statement.txt" in extra
    assert doc["id"] in extra


# ── review fixes ──────────────────────────────────────────────────


def test_status_separates_configured_and_scanned_folders(client, ext):
    """The panel must not advertise a folder the indexer would reject (1.4)."""
    status = client.get("/documents").get_json()
    assert status["folders"] == []            # nothing configured yet
    assert status["scan_folders"]             # the chat-upload dir still scans
    assert status["pdf_support"] is True
    assert status["documents_dir"] in status["scan_folders"]


def test_fava_documents_option_as_a_list_is_indexed(client, ext, tmp_path):
    """Beancount parses `option "documents" "documents"` as a LIST (1.4)."""
    from types import SimpleNamespace

    docs_dir = tmp_path / "documents"
    docs_dir.mkdir()
    (docs_dir / "receipt.md").write_text("Landlord: Example Properties, rent 1500")

    # This used to raise TypeError inside a swallowed except, so the folder was
    # silently dropped and /documents_index answered "no folders configured".
    ext.ledger.fava_options = SimpleNamespace(documents=["documents"])

    status = client.get("/documents").get_json()
    assert status["folders"] == [str(docs_dir)]

    resp = client.post("/documents_index", json={})
    assert resp.status_code == 200
    assert resp.get_json()["indexed"] == 1

    listed = client.get("/documents?all=1").get_json()
    assert [d["name"] for d in listed] == ["receipt.md"]


def test_embed_test_surfaces_the_real_error(client, ext, monkeypatch):
    """The UI reads `error`; it used to be reported as "unknown error" (2.1)."""
    import yaml

    (ext.config_dir / "config.yaml").write_text(yaml.dump({
        "documents": {"embedding": {
            "base_url": "http://127.0.0.1:1/v1", "model": "broken",
        }},
    }))
    ext._config_manager._load_yaml()
    ext._refresh_embedder()

    monkeypatch.setattr(
        ext._document_store.embedder, "test_connection",
        lambda: (False, "HTTP 500: model failed to load"),
    )
    payload = client.post("/documents_embed_test", json={}).get_json()
    assert payload["connected"] is False
    assert payload["error"] == "HTTP 500: model failed to load"
    assert payload["detail"] == payload["error"]


def test_retry_endpoint_reports_nothing_to_do(client, ext):
    payload = client.post("/documents_retry", json={}).get_json()
    assert payload["retried"] == 0
    assert payload["indexed"] == 0


def test_retry_endpoint_recovers_a_failed_pdf(client, ext, monkeypatch):
    """A PDF that failed extraction is recoverable without re-uploading (1.3)."""
    from fava_ai.documents import store as store_module
    from fava_ai.documents.extract import STATUS_INDEXED, STATUS_UNSUPPORTED, Extracted

    from tests.unit.test_documents import make_pdf

    real = store_module.extract_text
    monkeypatch.setattr(
        store_module, "extract_text",
        lambda *a, **k: Extracted(
            kind="pdf", status=STATUS_UNSUPPORTED, error="no pypdf"
        ),
    )
    resp = _upload(client, "invoice.pdf", make_pdf("Invoice 1234 Example Corp"))
    assert resp.get_json()["status"] == STATUS_UNSUPPORTED

    monkeypatch.setattr(store_module, "extract_text", real)
    payload = client.post("/documents_retry", json={}).get_json()
    assert payload["retried"] == 1 and payload["indexed"] == 1

    docs = client.get("/documents?all=1").get_json()
    assert docs[0]["status"] == STATUS_INDEXED


def test_delete_conversation_cleans_up_uploads(client, ext):
    """Deleting a conversation must not orphan its uploaded files (2.2)."""
    created = client.post("/conversations", json={"id": "conv-gone", "title": "t"})
    assert created.status_code == 201

    doc = _upload(client, "receipt.txt", conversation_id="conv-gone").get_json()
    upload_dir = ext._document_store.documents_dir / "conv-gone"
    assert (upload_dir / "receipt.txt").is_file()

    resp = client.delete("/conversations?id=conv-gone")
    assert resp.status_code == 200
    assert resp.get_json()["documents"]["documents"] == 1

    assert client.get(f"/documents?id={doc['id']}").status_code == 404
    assert client.get("/documents?conversation_id=conv-gone").get_json() == []
    assert not upload_dir.exists()


def test_config_round_trip_accepts_config_dir(client, ext, tmp_path):
    """GET returns config_dir; PUT must not reject it as an unknown key (2.4)."""
    (ext.config_dir / "config.yaml").write_text(yaml.dump({
        "agent": {"max_iterations": 4},
    }))
    ext._config_manager._load_yaml()

    config = client.get("/config").get_json()
    assert "config_dir" in config
    resp = client.put("/config", json=config)
    assert resp.status_code == 200, resp.get_json()

    written = yaml.safe_load((ext.config_dir / "config.yaml").read_text())
    assert "config_dir" not in written       # read-only, never persisted
    assert written["agent"]["max_iterations"] == 4


def test_put_config_still_rejects_a_lone_config_dir(client, ext):
    """Filtering config_dir must not turn an empty payload into a wipe (2.4)."""
    resp = client.put("/config", json={"config_dir": ".fava-ai"})
    assert resp.status_code == 400
