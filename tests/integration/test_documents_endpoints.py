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


def test_upload_tolerates_bytes_filename(client, ext):
    """Some clients send a bytes filename; it must not crash (py3.10 Werkzeug)."""
    resp = client.post(
        "/documents_upload",
        data={"file": (io.BytesIO(b"bytes name content"), b"from-bytes.txt")},
        content_type="multipart/form-data",
    )
    assert resp.status_code == 201
    assert resp.get_json()["name"].endswith("from-bytes.txt")


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
