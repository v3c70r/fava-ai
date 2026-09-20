"""Runtime error taxonomy, provenance and message-history tests."""

from pathlib import Path

import pytest
from fava_ai.agent.context import ContextBuilder
from fava_ai.agent.errors import (
    EmptyResponseError,
    LimitExceeded,
    ProviderError,
)
from fava_ai.agent.runtime import AgentRuntime
from fava_ai.config import ConfigManager
from fava_ai.models.base import BaseProvider, ChatResponse, FunctionCall
from fava_ai.models.base import ToolCall as LLMToolCall
from fava_ai.models.registry import ProviderRegistry
from fava_ai.tools.base import BaseTool, ToolResult
from fava_ai.tools.registry import ToolRegistry

from tests.conftest import MockLedger


class ScriptedProvider(BaseProvider):
    """Returns queued responses; can be told to raise instead."""

    def __init__(self, responses=None, error=None):
        self._responses = list(responses or [])
        self._error = error
        self._i = 0

    @property
    def provider_name(self):
        return "scripted"

    def chat(self, messages, tools=None, model=None, **kwargs):
        if self._error is not None:
            raise self._error
        resp = self._responses[min(self._i, len(self._responses) - 1)]
        self._i += 1
        return resp

    def chat_stream(self, messages, tools=None, model=None, **kwargs):
        yield from []

    def list_models(self):
        return []

    def test_connection(self):
        return True


class ErrorTool(BaseTool):
    """Returns a ToolResult whose metadata signals a handled error."""

    @property
    def name(self):
        return "error_tool"

    @property
    def description(self):
        return "Always reports an error"

    @property
    def parameters(self):
        return {"type": "object", "properties": {}}

    def execute(self, **kwargs):
        return ToolResult(
            content="Query Error: syntax",
            metadata={"error": "syntax", "bql": "SELECT bad"},
        )


def _make_agent(provider, tools=None, config=None):
    cm = ConfigManager(None, {"provider": "scripted"}, Path("/tmp"))
    reg = ProviderRegistry(cm)
    reg.register("scripted", provider)

    ledger = MockLedger([], {"operating_currency": ["USD"]})
    tool_reg = ToolRegistry()
    for tool in tools or []:
        tool_reg.register(tool)
    cb = ContextBuilder(ledger, tool_reg)

    return AgentRuntime(
        provider_registry=reg,
        tool_registry=tool_reg,
        context_builder=cb,
        config=config or {"max_iterations": 5, "max_tool_calls": 10},
    )


def test_empty_response_raises_empty_response_error():
    agent = _make_agent(ScriptedProvider([ChatResponse(content=None)]))
    with pytest.raises(EmptyResponseError):
        agent.run("hi", provider_name="scripted")


def test_provider_exception_is_wrapped():
    agent = _make_agent(ScriptedProvider(error=RuntimeError("connection reset")))
    with pytest.raises(ProviderError, match="connection reset"):
        agent.run("hi", provider_name="scripted")


def test_max_iterations_still_raises_limit_exceeded():
    responses = [
        ChatResponse(tool_calls=[
            LLMToolCall(id=str(i), function=FunctionCall(name="error_tool", arguments="{}"))
        ])
        for i in range(5)
    ]
    agent = _make_agent(
        ScriptedProvider(responses),
        tools=[ErrorTool()],
        config={"max_iterations": 2, "max_tool_calls": 10},
    )
    with pytest.raises(LimitExceeded):
        agent.run("hi", provider_name="scripted")


def test_final_assistant_message_is_included_in_new_messages():
    provider = ScriptedProvider([ChatResponse(content="final answer")])
    agent = _make_agent(provider)

    result = agent.run("my question", provider_name="scripted")

    roles = [m.role for m in result["new_messages"]]
    assert roles[0] == "user"
    assert roles[-1] == "assistant"
    assert result["new_messages"][-1].content == "final answer"
    # The system prompt is injected but must not be part of new_messages.
    assert all(m.role != "system" for m in result["new_messages"])


def test_tool_metadata_error_is_recorded_in_provenance():
    provider = ScriptedProvider([
        ChatResponse(tool_calls=[
            LLMToolCall(id="1", function=FunctionCall(name="error_tool", arguments="{}"))
        ]),
        ChatResponse(content="done"),
    ])
    agent = _make_agent(provider, tools=[ErrorTool()])

    result = agent.run("hi", provider_name="scripted")

    tool_steps = [
        s for s in result["provenance"]["steps"] if s["step_type"] == "tool_call"
    ]
    assert len(tool_steps) == 1
    assert tool_steps[0]["error"] == "syntax"


def test_tool_exception_is_recorded_in_provenance():
    class BoomTool(ErrorTool):
        @property
        def name(self):
            return "boom_tool"

        def execute(self, **kwargs):
            raise RuntimeError("kaboom")

    provider = ScriptedProvider([
        ChatResponse(tool_calls=[
            LLMToolCall(id="1", function=FunctionCall(name="boom_tool", arguments="{}"))
        ]),
        ChatResponse(content="recovered"),
    ])
    agent = _make_agent(provider, tools=[BoomTool()])

    result = agent.run("hi", provider_name="scripted")
    tool_steps = [
        s for s in result["provenance"]["steps"] if s["step_type"] == "tool_call"
    ]
    assert "kaboom" in tool_steps[0]["error"]
    # The failure is surfaced to the model rather than crashing the run.
    assert result["content"] == "recovered"


# ── retries ───────────────────────────────────────────────────────


class _FakeRateLimit(Exception):
    status_code = 429


class _FakeAuthError(Exception):
    status_code = 401


class _FakeTimeout(Exception):
    """Mimics litellm.Timeout (class name is what _is_timeout checks)."""


_FakeTimeout.__name__ = "Timeout"


class FlakyProvider(BaseProvider):
    def __init__(self, fail_times, exc):
        self._fail_times = fail_times
        self._exc = exc
        self.calls = 0

    @property
    def provider_name(self):
        return "flaky"

    def chat(self, messages, tools=None, model=None, **kwargs):
        self.calls += 1
        if self.calls <= self._fail_times:
            raise self._exc
        return ChatResponse(content="recovered")

    def chat_stream(self, messages, tools=None, model=None, **kwargs):
        yield from []

    def list_models(self):
        return []

    def test_connection(self):
        return True


def test_transient_provider_error_is_retried(monkeypatch):
    monkeypatch.setattr("fava_ai.agent.runtime.time.sleep", lambda _s: None)
    provider = FlakyProvider(fail_times=1, exc=_FakeRateLimit("slow down"))
    agent = _make_agent(provider, config={"retries": 2, "max_iterations": 3})

    result = agent.run("hi", provider_name="scripted")
    assert result["content"] == "recovered"
    assert provider.calls == 2


def test_auth_error_is_not_retried(monkeypatch):
    monkeypatch.setattr("fava_ai.agent.runtime.time.sleep", lambda _s: None)
    provider = FlakyProvider(fail_times=5, exc=_FakeAuthError("bad key"))
    agent = _make_agent(provider, config={"retries": 3, "max_iterations": 3})

    with pytest.raises(ProviderError, match="bad key"):
        agent.run("hi", provider_name="scripted")
    assert provider.calls == 1


def test_timeout_is_not_retried_and_maps_to_504(monkeypatch):
    """A read timeout must fail fast, not be retried (see eval findings)."""
    from fava_ai.agent.errors import ProviderTimeoutError

    monkeypatch.setattr("fava_ai.agent.runtime.time.sleep", lambda _s: None)
    provider = FlakyProvider(fail_times=5, exc=_FakeTimeout("too slow"))
    agent = _make_agent(provider, config={"retries": 3, "max_iterations": 3})

    with pytest.raises(ProviderTimeoutError) as excinfo:
        agent.run("hi", provider_name="scripted")

    assert excinfo.value.http_status == 504
    assert provider.calls == 1  # no retries


def test_deadline_exceeded_raises_timeout():
    from fava_ai.agent.errors import ProviderTimeoutError

    provider = FlakyProvider(fail_times=0, exc=RuntimeError("unused"))
    agent = _make_agent(provider, config={"timeout_seconds": 1, "max_iterations": 3})
    # Force the deadline into the past: the very first iteration must abort.
    agent._limits.timeout_seconds = -1
    with pytest.raises(ProviderTimeoutError):
        agent.run("hi", provider_name="scripted")
    assert provider.calls == 0


def test_max_tokens_passed_to_provider():
    captured = {}

    class RecordingProvider(ScriptedProvider):
        def chat(self, messages, tools=None, model=None, **kwargs):
            captured.update(kwargs)
            return ChatResponse(content="ok")

    provider = RecordingProvider([])
    agent = _make_agent(provider, config={"max_tokens": 256, "max_iterations": 2})
    agent.run("hi", provider_name="scripted")

    assert captured.get("max_tokens") == 256


# ── tool result cap & parallel calls ──────────────────────────────


class HugeTool(BaseTool):
    @property
    def name(self):
        return "huge"

    @property
    def description(self):
        return "returns a lot"

    @property
    def parameters(self):
        return {"type": "object", "properties": {}}

    def execute(self, **kwargs):
        return ToolResult(content="x" * 20000, metadata={})


def test_tool_result_is_capped_for_model():
    provider = ScriptedProvider([
        ChatResponse(tool_calls=[
            LLMToolCall(id="1", function=FunctionCall(name="huge", arguments="{}"))
        ]),
        ChatResponse(content="done"),
    ])
    agent = _make_agent(
        provider, tools=[HugeTool()],
        config={"max_tool_result_chars": 100, "max_iterations": 3},
    )

    result = agent.run("hi", provider_name="scripted")
    tool_message = next(m for m in result["messages"] if m.role == "tool")
    assert len(tool_message.content) < 200
    assert "truncated" in tool_message.content


def test_parallel_tool_calls_all_execute():
    class NamedTool(BaseTool):
        def __init__(self, name):
            self._name = name
            self.calls = 0

        @property
        def name(self):
            return self._name

        @property
        def description(self):
            return self._name

        @property
        def parameters(self):
            return {"type": "object", "properties": {}}

        def execute(self, **kwargs):
            self.calls += 1
            return ToolResult(content=f"{self._name} result", metadata={})

    a, b = NamedTool("tool_a"), NamedTool("tool_b")
    provider = ScriptedProvider([
        ChatResponse(tool_calls=[
            LLMToolCall(id="1", function=FunctionCall(name="tool_a", arguments="{}")),
            LLMToolCall(id="2", function=FunctionCall(name="tool_b", arguments="{}")),
        ]),
        ChatResponse(content="both done"),
    ])
    agent = _make_agent(provider, tools=[a, b])

    result = agent.run("hi", provider_name="scripted")
    assert a.calls == 1 and b.calls == 1
    tool_contents = [m.content for m in result["messages"] if m.role == "tool"]
    assert "tool_a result" in tool_contents
    assert "tool_b result" in tool_contents
