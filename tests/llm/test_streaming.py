"""Streaming tests: tool-call fragment reassembly and run_stream event flow."""

from pathlib import Path
from types import SimpleNamespace

import pytest
from fava_ai.agent.context import ContextBuilder
from fava_ai.agent.errors import (
    EmptyResponseError,
    LimitExceeded,
    ProviderError,
)
from fava_ai.agent.runtime import AgentRuntime
from fava_ai.config import ConfigManager
from fava_ai.models.base import (
    BaseProvider,
    FunctionCall,
    Message,
    StreamChunk,
)
from fava_ai.models.base import ToolCall as LLMToolCall
from fava_ai.models.registry import ProviderRegistry
from fava_ai.tools.base import BaseTool, ToolResult
from fava_ai.tools.registry import ToolRegistry

from tests.conftest import MockLedger

# ── litellm fragment reassembly ───────────────────────────────────


def _delta_tool_call(index, id=None, name=None, arguments=None):
    return SimpleNamespace(
        index=index,
        id=id,
        function=SimpleNamespace(name=name, arguments=arguments),
    )


def test_tool_call_accumulator_reassembles_fragments():
    from fava_ai.models.litellm_base import _ToolCallAccumulator

    acc = _ToolCallAccumulator()
    acc.add([_delta_tool_call(0, id="call_1", name="run_bql", arguments='{"q')])
    acc.add([_delta_tool_call(0, arguments='uery": "SELECT 1"}')])

    tool_calls = acc.to_tool_calls()
    assert len(tool_calls) == 1
    assert tool_calls[0].id == "call_1"
    assert tool_calls[0].function.name == "run_bql"
    assert tool_calls[0].function.arguments == '{"query": "SELECT 1"}'


def test_tool_call_accumulator_handles_multiple_parallel_calls():
    from fava_ai.models.litellm_base import _ToolCallAccumulator

    acc = _ToolCallAccumulator()
    acc.add([
        _delta_tool_call(0, id="a", name="t1", arguments="{"),
        _delta_tool_call(1, id="b", name="t2", arguments="{"),
    ])
    acc.add([
        _delta_tool_call(0, arguments="}"),
        _delta_tool_call(1, arguments="}"),
    ])

    tool_calls = acc.to_tool_calls()
    assert [tc.id for tc in tool_calls] == ["a", "b"]
    assert [tc.function.name for tc in tool_calls] == ["t1", "t2"]
    assert [tc.function.arguments for tc in tool_calls] == ["{}", "{}"]


def test_litellm_chat_stream_assembles_fragments(monkeypatch):
    import fava_ai.models.litellm_base as base
    from fava_ai.models.openai_compat import OpenAICompatProvider

    def _chunk(content=None, tool_calls=None, finish_reason=None):
        delta = SimpleNamespace(content=content, tool_calls=tool_calls)
        return SimpleNamespace(
            choices=[SimpleNamespace(delta=delta, finish_reason=finish_reason)]
        )

    chunks = [
        _chunk(tool_calls=[_delta_tool_call(0, id="call_1", name="run_bql", arguments='{"q')]),
        _chunk(tool_calls=[_delta_tool_call(0, arguments='uery": "x"}')]),
        _chunk(finish_reason="tool_calls"),
    ]
    monkeypatch.setattr(base.litellm, "completion", lambda **kw: iter(chunks))

    provider = OpenAICompatProvider(api_key="sk-x", model="gpt-4o")
    out = list(provider.chat_stream([Message(role="user", content="hi")]))

    assert all(c.content is None for c in out)
    final = out[-1]
    assert final.finish_reason == "tool_calls"
    assert final.tool_calls[0].function.name == "run_bql"
    assert final.tool_calls[0].function.arguments == '{"query": "x"}'


def test_litellm_chat_stream_yields_reasoning_deltas(monkeypatch):
    import fava_ai.models.litellm_base as base
    from fava_ai.models.openai_compat import OpenAICompatProvider

    def _chunk(reasoning=None, content=None, finish_reason=None):
        delta = SimpleNamespace(
            content=content, tool_calls=None, reasoning_content=reasoning
        )
        return SimpleNamespace(
            choices=[SimpleNamespace(delta=delta, finish_reason=finish_reason)]
        )

    monkeypatch.setattr(base.litellm, "completion", lambda **kw: iter([
        _chunk(reasoning="Let me "),
        _chunk(reasoning="think."),
        _chunk(content="42"),
        _chunk(finish_reason="stop"),
    ]))

    provider = OpenAICompatProvider(api_key="sk-x", model="gpt-4o")
    out = list(provider.chat_stream([Message(role="user", content="hi")]))

    reasoning = "".join(c.reasoning for c in out if c.reasoning)
    assert reasoning == "Let me think."
    assert "".join(c.content for c in out if c.content) == "42"


def test_litellm_chat_captures_reasoning(monkeypatch):
    import fava_ai.models.litellm_base as base
    from fava_ai.models.openai_compat import OpenAICompatProvider

    message = SimpleNamespace(
        content="4", tool_calls=None, reasoning_content="2+2 is 4"
    )
    response = SimpleNamespace(
        choices=[SimpleNamespace(message=message, finish_reason="stop")],
        usage=None,
    )
    monkeypatch.setattr(base.litellm, "completion", lambda **kw: response)

    provider = OpenAICompatProvider(api_key="sk-x", model="gpt-4o")
    result = provider.chat([Message(role="user", content="2+2?")])

    assert result.content == "4"
    assert result.reasoning == "2+2 is 4"


def test_litellm_chat_stream_yields_content_deltas(monkeypatch):
    import fava_ai.models.litellm_base as base
    from fava_ai.models.openai_compat import OpenAICompatProvider

    def _chunk(content=None, finish_reason=None):
        delta = SimpleNamespace(content=content, tool_calls=None)
        return SimpleNamespace(
            choices=[SimpleNamespace(delta=delta, finish_reason=finish_reason)]
        )

    monkeypatch.setattr(
        base.litellm, "completion",
        lambda **kw: iter([_chunk("Hel"), _chunk("lo"), _chunk(finish_reason="stop")]),
    )

    provider = OpenAICompatProvider(api_key="sk-x", model="gpt-4o")
    out = list(provider.chat_stream([Message(role="user", content="hi")]))

    assert "".join(c.content for c in out if c.content) == "Hello"
    assert out[-1].finish_reason == "stop"


# ── run_stream event flow ─────────────────────────────────────────


class StreamProvider(BaseProvider):
    """Yields a scripted list of StreamChunks per call."""

    def __init__(self, scripts):
        self._scripts = scripts
        self._i = 0

    @property
    def provider_name(self):
        return "stream"

    def chat(self, messages, tools=None, model=None, **kwargs):
        raise AssertionError("run_stream must not call chat()")

    def chat_stream(self, messages, tools=None, model=None, **kwargs):
        script = self._scripts[min(self._i, len(self._scripts) - 1)]
        self._i += 1
        yield from script

    def list_models(self):
        return []

    def test_connection(self):
        return True


class CountingTool(BaseTool):
    def __init__(self):
        self.calls = 0

    @property
    def name(self):
        return "echo"

    @property
    def description(self):
        return "echo"

    @property
    def parameters(self):
        return {"type": "object", "properties": {}}

    def execute(self, **kwargs):
        self.calls += 1
        return ToolResult(content="echoed", metadata={})


def _make_agent(provider, tools=None, config=None, prompt_registry=None):
    cm = ConfigManager(None, {"provider": "stream"}, Path("/tmp"))
    reg = ProviderRegistry(cm)
    reg.register("stream", provider)

    ledger = MockLedger([], {"operating_currency": ["USD"]})
    tool_reg = ToolRegistry()
    for tool in tools or []:
        tool_reg.register(tool)
    cb = ContextBuilder(ledger, tool_reg, prompt_registry=prompt_registry)

    return AgentRuntime(
        provider_registry=reg,
        tool_registry=tool_reg,
        context_builder=cb,
        config=config or {"max_iterations": 5, "max_tool_calls": 10},
    )


def test_run_stream_content_only():
    provider = StreamProvider([[
        StreamChunk(content="Hel"),
        StreamChunk(content="lo"),
        StreamChunk(finish_reason="stop"),
    ]])
    agent = _make_agent(provider)

    events = list(agent.run_stream("hi", provider_name="stream"))

    deltas = [e["content"] for e in events if e["type"] == "content_delta"]
    assert deltas == ["Hel", "lo"]
    assert events[-1]["type"] == "done"
    result = events[-1]["result"]
    assert result["content"] == "Hello"
    assert result["new_messages"][-1].role == "assistant"


def test_run_stream_tool_call_loop():
    tool = CountingTool()
    provider = StreamProvider([
        [
            StreamChunk(tool_calls=[
                LLMToolCall(id="1", function=FunctionCall(name="echo", arguments="{}"))
            ]),
            StreamChunk(finish_reason="tool_calls"),
        ],
        [StreamChunk(content="final"), StreamChunk(finish_reason="stop")],
    ])
    agent = _make_agent(provider, tools=[tool])

    events = list(agent.run_stream("hi", provider_name="stream"))
    types = [e["type"] for e in events]

    assert "tool_call_start" in types
    assert "tool_call" in types
    assert types[-1] == "done"
    assert tool.calls == 1
    assert events[-1]["result"]["content"] == "final"

    # The tool result is present in the message history sent to the model.
    tool_steps = [e for e in events if e["type"] == "tool_call"]
    assert tool_steps[0]["step"]["tool_name"] == "echo"


def test_run_stream_max_iterations_returns_partial():
    provider = StreamProvider([[
        StreamChunk(tool_calls=[
            LLMToolCall(id="1", function=FunctionCall(name="echo", arguments="{}"))
        ]),
        StreamChunk(finish_reason="tool_calls"),
    ]])
    agent = _make_agent(
        provider, tools=[CountingTool()],
        config={"max_iterations": 2, "max_tool_calls": 10},
    )

    events = list(agent.run_stream("hi", provider_name="stream"))

    assert events[-1]["type"] == "done"
    result = events[-1]["result"]
    assert result["partial"] is True
    assert "max_iterations" in result["stop_reason"]
    # A partial answer is streamed before the done event.
    assert any(e["type"] == "content_delta" for e in events)


def test_run_stream_empty_raises():
    provider = StreamProvider([[StreamChunk(finish_reason="stop")]])
    agent = _make_agent(provider)

    with pytest.raises(EmptyResponseError):
        list(agent.run_stream("hi", provider_name="stream"))


def test_run_stream_provider_error_wrapped():
    class BoomProvider(StreamProvider):
        def chat_stream(self, messages, tools=None, model=None, **kwargs):
            raise RuntimeError("stream exploded")
            yield  # pragma: no cover

    agent = _make_agent(BoomProvider([]))
    with pytest.raises(ProviderError, match="stream exploded"):
        list(agent.run_stream("hi", provider_name="stream"))


def test_run_stream_emits_reasoning_deltas():
    provider = StreamProvider([[
        StreamChunk(reasoning="Let me think..."),
        StreamChunk(content="Answer"),
        StreamChunk(finish_reason="stop"),
    ]])
    agent = _make_agent(provider)

    events = list(agent.run_stream("hi", provider_name="stream"))

    assert events[0]["type"] == "reasoning_delta"
    reasoning = "".join(
        e["content"] for e in events if e["type"] == "reasoning_delta"
    )
    assert reasoning == "Let me think..."
    assert events[-1]["type"] == "done"


class FlakyStreamProvider(BaseProvider):
    """Fails N times with a retryable error, optionally after streaming reasoning."""

    def __init__(self, fail_times, after_reasoning=False):
        self._fail_times = fail_times
        self._after_reasoning = after_reasoning
        self.calls = 0

    @property
    def provider_name(self):
        return "flaky-stream"

    def chat(self, messages, tools=None, model=None, **kwargs):
        raise AssertionError("run_stream must not call chat()")

    def chat_stream(self, messages, tools=None, model=None, **kwargs):
        self.calls += 1
        if self.calls <= self._fail_times:
            if self._after_reasoning:
                yield StreamChunk(reasoning="partial thought")
            raise ConnectionError("connection reset")
        yield StreamChunk(content="recovered")
        yield StreamChunk(finish_reason="stop")

    def list_models(self):
        return []

    def test_connection(self):
        return True


def test_run_stream_retries_when_nothing_streamed(monkeypatch):
    monkeypatch.setattr("fava_ai.agent.runtime.time.sleep", lambda _s: None)
    provider = FlakyStreamProvider(fail_times=1)
    agent = _make_agent(provider, config={"retries": 2, "max_iterations": 3})

    events = list(agent.run_stream("hi", provider_name="stream"))

    assert provider.calls == 2
    assert events[-1]["type"] == "done"
    assert events[-1]["result"]["content"] == "recovered"


def test_run_stream_does_not_retry_after_reasoning_streamed(monkeypatch):
    """Retrying after reasoning was rendered would duplicate the Thinking block."""
    monkeypatch.setattr("fava_ai.agent.runtime.time.sleep", lambda _s: None)
    provider = FlakyStreamProvider(fail_times=1, after_reasoning=True)
    agent = _make_agent(provider, config={"retries": 2, "max_iterations": 3})

    with pytest.raises(ProviderError, match="connection reset"):
        list(agent.run_stream("hi", provider_name="stream"))

    assert provider.calls == 1


def test_run_stream_passes_model_and_prompt():
    from fava_ai.prompts.registry import PromptRegistry

    provider = StreamProvider([[StreamChunk(content="ok"), StreamChunk(finish_reason="stop")]])
    agent = _make_agent(provider, prompt_registry=PromptRegistry())

    captured = {}

    class RecordingProvider(StreamProvider):
        def chat_stream(self, messages, tools=None, model=None, **kwargs):
            captured["model"] = model
            captured["system"] = messages[0].content
            yield StreamChunk(content="ok")
            yield StreamChunk(finish_reason="stop")

    agent._provider_registry.register("rec", RecordingProvider([]))
    list(agent.run_stream("hi", provider_name="rec", model="gpt-4o-mini", prompt_id="monthly_review"))

    assert captured["model"] == "gpt-4o-mini"
    assert "financial review" in captured["system"].lower()
