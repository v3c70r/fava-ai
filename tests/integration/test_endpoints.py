"""Layer 3: endpoint tests via the Flask test client."""

import json

import pytest

from tests.integration.conftest import StubRuntime, make_result

# ── chat ──────────────────────────────────────────────────────────


def test_chat_persists_and_returns_message_id(client, ext):
    ext._agent_runtime = StubRuntime(make_result())

    resp = client.post("/chat", json={"message": "hello"})
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["content"] == "The answer is 42."
    assert data["conversation_id"]
    assert data["message_id"]

    # Conversation history contains the final assistant answer.
    conv = client.get(f"/conversations?id={data['conversation_id']}").get_json()
    roles = [m["role"] for m in conv["messages"]]
    assert roles == ["user", "assistant"]
    assert conv["messages"][-1]["content"] == "The answer is 42."


def test_chat_persists_traces(client, ext):
    ext._agent_runtime = StubRuntime(make_result(tool_name="run_bql"))

    resp = client.post("/chat", json={"message": "hello"})
    message_id = resp.get_json()["message_id"]

    traces = client.get(f"/traces?message_id={message_id}").get_json()
    step_types = [t["step_type"] for t in traces]
    assert "plan" in step_types
    assert "tool_call" in step_types
    assert "synthesis" in step_types
    tool_step = next(t for t in traces if t["step_type"] == "tool_call")
    assert tool_step["tool_name"] == "run_bql"


def test_chat_requires_message(client, ext):
    resp = client.post("/chat", json={})
    assert resp.status_code == 400


@pytest.mark.parametrize(
    "error_name,expected_status",
    [
        ("LimitExceeded", 429),
        ("ProviderError", 502),
        ("EmptyResponseError", 502),
        ("NoProviderError", 503),
    ],
)
def test_chat_error_taxonomy_maps_to_http_status(client, ext, error_name, expected_status):
    import fava_ai.agent.errors as errors

    ext._agent_runtime = StubRuntime(error=getattr(errors, error_name)("boom"))
    resp = client.post("/chat", json={"message": "hello"})
    assert resp.status_code == expected_status
    body = resp.get_json()
    assert body["error_type"] == error_name
    assert "boom" in body["error"]


def test_chat_stream_emits_frames_and_persists(client, ext):
    ext._agent_runtime = StubRuntime(make_result(tool_name="ledger_info"))

    resp = client.post("/chat_stream", json={"message": "hello"})
    assert resp.status_code == 200
    assert resp.mimetype == "text/event-stream"

    frames = _parse_sse(resp.get_data(as_text=True))
    types = [f["type"] for f in frames]
    assert "content" in types
    assert "tool_call" in types
    assert types[-1] == "done"
    assert frames[-1]["message_id"]


def test_chat_stream_error_frame(client, ext):
    from fava_ai.agent.errors import ProviderError

    ext._agent_runtime = StubRuntime(error=ProviderError("nope"))
    resp = client.post("/chat_stream", json={"message": "hello"})
    frames = _parse_sse(resp.get_data(as_text=True))
    assert frames[-1]["type"] == "error"
    assert frames[-1]["error_type"] == "ProviderError"


# ── conversations ─────────────────────────────────────────────────


def test_conversation_crud(client, ext):
    created = client.post("/conversations", json={"title": "T"}).get_json()
    conv_id = created["id"]
    assert created["title"] == "T"

    listed = client.get("/conversations").get_json()
    assert any(c["id"] == conv_id for c in listed)

    fetched = client.get(f"/conversations?id={conv_id}").get_json()
    assert fetched["id"] == conv_id

    deleted = client.delete(f"/conversations?id={conv_id}")
    assert deleted.get_json()["deleted"] is True
    assert client.get(f"/conversations?id={conv_id}").status_code == 404


def test_create_conversation_duplicate_id_returns_409(client, ext):
    first = client.post("/conversations", json={"id": "dup", "title": "A"})
    assert first.status_code == 201
    second = client.post("/conversations", json={"id": "dup", "title": "B"})
    assert second.status_code == 409


def test_delete_missing_conversation_returns_404(client, ext):
    assert client.delete("/conversations?id=nope").status_code == 404


# ── config ────────────────────────────────────────────────────────


def test_get_config_masks_api_keys(client, ext, tmp_path):
    import yaml

    (ext.config_dir / "config.yaml").write_text(yaml.dump({
        "providers": {"openai": {"api_key": "sk-real", "model": "gpt-4o"}},
    }))
    ext._config_manager._load_yaml()

    body = client.get("/config").get_json()
    assert body["providers"]["openai"]["api_key"] == "***"


def test_put_config_preserves_masked_env_reference(client, ext):
    import yaml

    config_path = ext.config_dir / "config.yaml"
    config_path.write_text(yaml.dump({
        "providers": {"openai": {"api_key": "${OPENAI_API_KEY}", "model": "gpt-4o"}},
    }))
    ext._config_manager._load_yaml()

    # Simulate a UI round-trip: GET returns "***", then PUT sends it back.
    put_body = {
        "providers": {"openai": {"api_key": "***", "model": "gpt-4o-mini"}},
    }
    resp = client.put("/config", json=put_body)
    assert resp.status_code == 200

    written = yaml.safe_load(config_path.read_text())
    assert written["providers"]["openai"]["api_key"] == "${OPENAI_API_KEY}"
    assert written["providers"]["openai"]["model"] == "gpt-4o-mini"


def test_put_config_rejects_non_object(client, ext):
    resp = client.put("/config", json=[1, 2, 3])
    assert resp.status_code == 400


@pytest.mark.parametrize(
    "payload",
    [
        {"evil_top_level": 1},
        {"providers": {"not-a-provider": {}}},
        {"providers": {"openai": {"shell": "rm -rf /"}}},
        {"agent": {"max_iterations": "lots"}},
        {"knowledge": {"auto_extract": "yes"}},
    ],
)
def test_put_config_rejects_invalid_documents(client, ext, payload):
    resp = client.put("/config", json=payload)
    assert resp.status_code == 400
    assert "details" in resp.get_json()


def test_put_config_invalid_document_does_not_write(client, ext):
    config_path = ext.config_dir / "config.yaml"
    config_path.write_text("providers:\n  openai:\n    model: gpt-4o\n")
    ext._config_manager._load_yaml()

    resp = client.put("/config", json={"bogus": True})
    assert resp.status_code == 400
    # File is untouched.
    assert "openai" in config_path.read_text()


# ── tools / prompts / knowledge ───────────────────────────────────


def test_tools_listing_and_404(client, ext):
    tools = client.get("/tools").get_json()
    names = {t["name"] for t in tools}
    assert "run_bql" in names

    assert client.get("/tools?name=nope").status_code == 404
    single = client.get("/tools?name=run_bql").get_json()
    assert single["name"] == "run_bql"


def test_prompts_listing_and_404(client, ext):
    prompts = client.get("/prompts").get_json()
    assert any(p["id"] == "default" for p in prompts)
    assert client.get("/prompts?name=nope").status_code == 404


def test_knowledge_status(client, ext):
    body = client.get("/knowledge?action=status").get_json()
    assert body["enabled"] is True


# ── after_load_file ───────────────────────────────────────────────


class _RaisingEngine:
    def needs_rebuild(self, entries):
        return True

    def extract_all(self, entries, options):
        raise RuntimeError("extraction blew up")


def test_after_load_file_logs_instead_of_raising(client, ext, caplog):
    ext._knowledge_engine = _RaisingEngine()
    with caplog.at_level("ERROR"):
        ext.after_load_file()  # must not raise
    assert any("extraction failed" in r.message.lower() for r in caplog.records)


def test_after_load_file_skips_when_disabled(client, ext):
    ext._knowledge_engine = _RaisingEngine()
    ext._config_manager._yaml_config = {"knowledge": {"auto_extract": False}}
    ext.after_load_file()  # no engine call, no raise


# ── helpers ───────────────────────────────────────────────────────


def _parse_sse(text: str) -> list[dict]:
    frames = []
    for line in text.splitlines():
        line = line.strip()
        if line.startswith("data:"):
            frames.append(json.loads(line[len("data:"):].strip()))
    return frames
