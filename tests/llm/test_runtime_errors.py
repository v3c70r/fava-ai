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
