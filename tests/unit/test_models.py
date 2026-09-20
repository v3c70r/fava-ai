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

    cm = ConfigManager(None, {"provider": "ollama"}, __import__("pathlib").Path("/tmp"))
    reg = ProviderRegistry(cm)
    ollama = reg.get("ollama")
    assert ollama is not None
    assert ollama.provider_name == "ollama"


def test_provider_registry_default():
    from fava_ai.config import ConfigManager
    from fava_ai.models.registry import ProviderRegistry

    cm = ConfigManager(None, {"provider": "ollama"}, __import__("pathlib").Path("/tmp"))
    reg = ProviderRegistry(cm)
    default = reg.get_default()
    assert default is not None
    assert default.provider_name == "ollama"


def test_provider_registry_list():
    from fava_ai.config import ConfigManager
    from fava_ai.models.registry import ProviderRegistry

    cm = ConfigManager(None, {"provider": "ollama"}, __import__("pathlib").Path("/tmp"))
    reg = ProviderRegistry(cm)
    providers = reg.list_providers()
    assert len(providers) == 1
    assert providers[0]["name"] == "ollama"
    assert providers[0]["is_default"] is True


def test_provider_registry_empty_returns_none(tmp_dir):
    """No configured provider must yield None, not a silent Ollama fallback."""
    from fava_ai.config import ConfigManager
    from fava_ai.models.registry import ProviderRegistry

    cm = ConfigManager(None, {}, tmp_dir)
    reg = ProviderRegistry(cm)
    assert reg.get_default() is None
    assert reg.list_providers() == []


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
