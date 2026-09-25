"""Unit tests for models/ modules."""
import pytest
from fava_ai.models.base import (
    ChatResponse,
    FunctionCall,
    Message,
    StreamChunk,
    ToolCall,
)


def test_message_to_litellm_user():
    msg = Message(role="user", content="Hello")
    d = msg.to_litellm()
    assert d == {"role": "user", "content": "Hello"}


def test_message_to_litellm_assistant_with_tool_calls():
    tc = ToolCall(id="1", function=FunctionCall(name="test", arguments="{}"))
    msg = Message(role="assistant", tool_calls=[tc])
    d = msg.to_litellm()
    assert d["role"] == "assistant"
    assert "content" not in d
    assert len(d["tool_calls"]) == 1
    assert d["tool_calls"][0]["id"] == "1"
    assert d["tool_calls"][0]["type"] == "function"
    assert d["tool_calls"][0]["function"]["name"] == "test"


def test_message_to_litellm_tool():
    msg = Message(
        role="tool", content="result", tool_call_id="call_1", name="ledger_info"
    )
    d = msg.to_litellm()
    assert d["role"] == "tool"
    assert d["content"] == "result"
    assert d["tool_call_id"] == "call_1"
    assert d["name"] == "ledger_info"


def test_tool_call_to_dict():
    tc = ToolCall(id="1", function=FunctionCall(name="test", arguments='{"x": 1}'))
    d = tc.to_dict()
    assert d["id"] == "1"
    assert d["type"] == "function"
    assert d["function"]["name"] == "test"
    assert d["function"]["arguments"] == '{"x": 1}'


def test_chat_response_has_tool_calls():
    r = ChatResponse(content="hello")
    assert not r.has_tool_calls()

    tc = ToolCall(id="1", function=FunctionCall(name="test", arguments="{}"))
    r2 = ChatResponse(tool_calls=[tc])
    assert r2.has_tool_calls()


def test_chat_response_as_message():
    tc = ToolCall(id="1", function=FunctionCall(name="test", arguments="{}"))
    r = ChatResponse(tool_calls=[tc], content=None)
    msg = r.as_message()
    assert msg.role == "assistant"
    assert msg.tool_calls == [tc]
    assert msg.content is None


def test_stream_chunk_defaults():
    chunk = StreamChunk()
    assert chunk.content is None
    assert chunk.tool_calls is None
    assert chunk.finish_reason is None


def test_message_none_content():
    msg = Message(role="assistant", content=None)
    d = msg.to_litellm()
    assert "content" not in d


def test_provider_registry():
    from fava_ai.config import ConfigManager
    from fava_ai.models.registry import ProviderRegistry

    cm = ConfigManager(None, {"provider": "openai"}, __import__("pathlib").Path("/tmp"))
    reg = ProviderRegistry(cm)
    openai = reg.get("openai")
    assert openai is not None
    # The vendor alias resolves to the single OpenAI-compatible implementation.
    assert openai.provider_name == "openai_compat"
    assert openai.base_url == "https://api.openai.com/v1"


def test_provider_registry_default():
    from fava_ai.config import ConfigManager
    from fava_ai.models.registry import ProviderRegistry

    cm = ConfigManager(None, {"provider": "openai"}, __import__("pathlib").Path("/tmp"))
    reg = ProviderRegistry(cm)
    default = reg.get_default()
    assert default is not None
    assert default.provider_name == "openai_compat"


def test_provider_registry_default_is_first_when_unspecified(tmp_dir):
    from fava_ai.config import ConfigManager
    from fava_ai.models.registry import ProviderRegistry

    cm = ConfigManager(None, {
        "providers": {
            "a": {"base_url": "http://a/v1", "model": "m"},
            "b": {"base_url": "http://b/v1", "model": "m"},
        }
    }, tmp_dir)
    reg = ProviderRegistry(cm)
    assert reg.get_default() is reg.get("a")
    assert [p["name"] for p in reg.list_providers()] == ["a", "b"]
    assert reg.list_providers()[0]["is_default"] is True


def test_provider_registry_flat_single_endpoint(tmp_dir):
    """A single endpoint can be declared flat in the beancount directive."""
    from fava_ai.config import ConfigManager
    from fava_ai.models.registry import ProviderRegistry

    cm = ConfigManager(None, {
        "provider": "local",
        "base_url": "http://localhost:8080/v1",
        "api_key": "k",
        "model": "my-model",
    }, tmp_dir)
    reg = ProviderRegistry(cm)

    provider = reg.get("local")
    assert provider is not None
    assert provider.base_url == "http://localhost:8080/v1"
    assert provider.api_key == "k"
    # Arbitrary name + base_url needs no explicit type.
    assert provider.provider_name == "openai_compat"


def test_provider_registry_list():
    from fava_ai.config import ConfigManager
    from fava_ai.models.registry import ProviderRegistry

    cm = ConfigManager(None, {"provider": "openai"}, __import__("pathlib").Path("/tmp"))
    reg = ProviderRegistry(cm)
    providers = reg.list_providers()
    assert len(providers) == 1
    assert providers[0]["name"] == "openai"
    assert providers[0]["is_default"] is True


def test_provider_registry_empty_returns_none(tmp_dir):
    """No configured provider must yield None, not a silent Ollama fallback."""
    from fava_ai.config import ConfigManager
    from fava_ai.models.registry import ProviderRegistry

    cm = ConfigManager(None, {}, tmp_dir)
    reg = ProviderRegistry(cm)
    assert reg.get_default() is None
    assert reg.list_providers() == []


def test_provider_registry_alias_with_explicit_type(tmp_dir):
    """Arbitrary provider names work when a `type` names the implementation."""
    (tmp_dir / "config.yaml").write_text(
        "providers:\n"
        "  local:\n"
        "    type: openai_compat\n"
        "    base_url: http://localhost:8080/v1\n"
        "    api_key: t\n"
        "    model: m\n"
    )
    from fava_ai.config import ConfigManager
    from fava_ai.models.registry import ProviderRegistry

    cm = ConfigManager(None, {"provider": "local"}, tmp_dir)
    reg = ProviderRegistry(cm)

    provider = reg.get("local")
    assert provider is not None
    assert provider.provider_name == "openai_compat"
    assert reg.get_default() is provider


def test_provider_registry_unknown_name_without_type_is_logged(tmp_dir, caplog):
    (tmp_dir / "config.yaml").write_text(
        "providers:\n  mystery:\n    model: m\n"
    )
    from fava_ai.config import ConfigManager
    from fava_ai.models.registry import ProviderRegistry

    cm = ConfigManager(None, {}, tmp_dir)
    with caplog.at_level("ERROR"):
        reg = ProviderRegistry(cm)

    assert reg.get("mystery") is None
    assert any("mystery" in r.message for r in caplog.records)


def test_provider_registry_alias_of(tmp_dir):
    from fava_ai.config import ConfigManager
    from fava_ai.models.base import BaseProvider, ChatResponse
    from fava_ai.models.registry import ProviderRegistry

    class FakeProvider(BaseProvider):
        @property
        def provider_name(self):
            return "fake-type"

        def chat(self, messages, tools=None, model=None, **kwargs):
            return ChatResponse(content="ok")

        def chat_stream(self, messages, tools=None, model=None, **kwargs):
            yield from []

        def list_models(self):
            return []

        def test_connection(self):
            return True

    cm = ConfigManager(None, {}, tmp_dir)
    reg = ProviderRegistry(cm)
    provider = FakeProvider()
    reg.register("alias-a", provider)

    assert reg.alias_of(provider) == "alias-a"
    assert reg.alias_of(FakeProvider()) is None


def test_provider_registry_connection_cache_invalidate():
    from fava_ai.config import ConfigManager
    from fava_ai.models.registry import ProviderRegistry

    cm = ConfigManager(None, {}, __import__("pathlib").Path("/tmp"))
    reg = ProviderRegistry(cm)
    reg.set_connection("a", True)
    reg.set_connection("b", False)
    assert reg._connection_cache == {"a": True, "b": False}

    reg.invalidate("a")
    assert "a" not in reg._connection_cache
    assert "b" in reg._connection_cache

    reg.invalidate()
    assert reg._connection_cache == {}


def test_provider_registry_reload_picks_up_config_changes(tmp_dir):
    """A key saved via PUT /config must not need a Fava restart (round 3, N6)."""
    from fava_ai.config import ConfigManager
    from fava_ai.models.registry import ProviderRegistry

    cm = ConfigManager(None, {
        "providers": {"local": {
            "base_url": "http://localhost:8080/v1", "api_key": "old", "model": "m",
        }},
    }, tmp_dir)
    reg = ProviderRegistry(cm)
    stale = reg.get("local")
    assert stale.api_key == "old"

    cm._extension_config = {
        "providers": {"local": {
            "base_url": "http://localhost:8080/v1", "api_key": "new", "model": "m",
        }},
    }
    reg.reload()

    assert reg.get("local").api_key == "new"
    assert reg.get("local") is not stale


def test_provider_registry_reload_drops_removed_providers(tmp_dir):
    from fava_ai.config import ConfigManager
    from fava_ai.models.registry import ProviderRegistry

    cm = ConfigManager(None, {
        "providers": {
            "a": {"base_url": "http://a/v1", "model": "m"},
            "b": {"base_url": "http://b/v1", "model": "m"},
        },
    }, tmp_dir)
    reg = ProviderRegistry(cm)
    assert reg.get("b") is not None

    cm._extension_config = {"providers": {"a": {"base_url": "http://a/v1", "model": "m"}}}
    reg.reload()
    assert reg.get("b") is None
    assert reg.get("a") is not None
