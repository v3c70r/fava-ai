"""Layer 4: LLM interaction tests with mock provider."""
import pytest
import json

from fava_ai.models.base import (
    BaseProvider,
    Message,
    ChatResponse,
    ToolCall,
    FunctionCall,
)
from fava_ai.agent.limits import ExecutionLimits, LimitExceeded


class MockProvider(BaseProvider):
    """Mock provider that returns predetermined responses."""
    def __init__(self, responses: list[ChatResponse]):
        self.responses = responses
        self.call_index = 0
        self.calls = []
        self._name = "mock"

    @property
    def provider_name(self) -> str:
        return self._name

    def chat(self, messages, tools=None, model=None, **kwargs):
        self.calls.append({"messages": messages, "tools": tools})
        if self.call_index >= len(self.responses):
            return ChatResponse(content="fallback")
        response = self.responses[self.call_index]
        self.call_index += 1
        return response

    def chat_stream(self, messages, tools=None, model=None, **kwargs):
        yield from []

    def list_models(self):
        return ["mock-model"]

    def test_connection(self):
        return True


def test_agent_single_step():
    from fava_ai.agent.runtime import AgentRuntime
    from fava_ai.tools.registry import ToolRegistry
    from fava_ai.tools.builtin.ledger import register_ledger_tools
    from fava_ai.agent.context import ContextBuilder
    from fava_ai.models.registry import ProviderRegistry
    from fava_ai.config import ConfigManager
    from tests.conftest import MockLedger

    provider = MockProvider([
        ChatResponse(content="You have 58 accounts."),
    ])

    cm = ConfigManager(None, {"provider": "mock"}, __import__("pathlib").Path("/tmp"))
    reg = ProviderRegistry(cm)
    reg.register("mock", provider)

    ledger = MockLedger([], {"operating_currency": ["USD"]})
    tool_reg = ToolRegistry()
    register_ledger_tools(tool_reg, ledger)
    cb = ContextBuilder(ledger, tool_reg)

    agent = AgentRuntime(
        provider_registry=reg,
        tool_registry=tool_reg,
        context_builder=cb,
        config={"max_iterations": 3, "max_tool_calls": 5},
    )

    result = agent.run("How many accounts?", provider_name="mock")
    assert "58 accounts" in result["content"]
    assert result["tool_call_count"] == 0
    assert "provenance" in result


def test_agent_tool_calling_loop():
    from fava_ai.agent.runtime import AgentRuntime
    from fava_ai.tools.registry import ToolRegistry
    from fava_ai.tools.builtin.ledger import register_ledger_tools
    from fava_ai.agent.context import ContextBuilder
    from fava_ai.models.registry import ProviderRegistry
    from fava_ai.config import ConfigManager
    from tests.conftest import MockLedger
    from fava_ai.tools.builtin.ledger import LedgerInfoTool

    provider = MockProvider([
        ChatResponse(tool_calls=[
            ToolCall(id="1", function=FunctionCall(
                name="ledger_info", arguments="{}"
            ))
        ]),
        ChatResponse(content="Your operating currency is USD."),
    ])

    cm = ConfigManager(None, {"provider": "mock"}, __import__("pathlib").Path("/tmp"))
    reg = ProviderRegistry(cm)
    reg.register("mock", provider)

    ledger = MockLedger([], {"operating_currency": ["USD"]})
    tool_reg = ToolRegistry()
    register_ledger_tools(tool_reg, ledger)
    cb = ContextBuilder(ledger, tool_reg)

    agent = AgentRuntime(
        provider_registry=reg,
        tool_registry=tool_reg,
        context_builder=cb,
        config={"max_iterations": 5, "max_tool_calls": 10},
    )

    result = agent.run("What currency?", provider_name="mock")
    assert "USD" in result["content"]
    assert result["tool_call_count"] == 1
    provenance = result.get("provenance", {})
    assert provenance.get("total_tool_calls") == 1


def test_agent_max_iterations():
    from fava_ai.agent.runtime import AgentRuntime
    from fava_ai.tools.registry import ToolRegistry
    from fava_ai.tools.builtin.ledger import register_ledger_tools
    from fava_ai.agent.context import ContextBuilder
    from fava_ai.models.registry import ProviderRegistry
    from fava_ai.config import ConfigManager
    from tests.conftest import MockLedger

    provider = MockProvider([
        ChatResponse(tool_calls=[
            ToolCall(id=f"call_{i}", function=FunctionCall(
                name="ledger_info", arguments="{}"
            ))
        ])
        for i in range(10)
    ])

    cm = ConfigManager(None, {"provider": "mock"}, __import__("pathlib").Path("/tmp"))
    reg = ProviderRegistry(cm)
    reg.register("mock", provider)

    ledger = MockLedger([], {"operating_currency": ["USD"]})
    tool_reg = ToolRegistry()
    register_ledger_tools(tool_reg, ledger)
    cb = ContextBuilder(ledger, tool_reg)

    agent = AgentRuntime(
        provider_registry=reg,
        tool_registry=tool_reg,
        context_builder=cb,
        config={"max_iterations": 3, "max_tool_calls": 10},
    )

    with pytest.raises(LimitExceeded):
        agent.run("Test", provider_name="mock")


def test_agent_tool_error_handling():
    from fava_ai.agent.runtime import AgentRuntime
    from fava_ai.tools.registry import ToolRegistry
    from fava_ai.tools.builtin.ledger import register_ledger_tools
    from fava_ai.agent.context import ContextBuilder
    from fava_ai.models.registry import ProviderRegistry
    from fava_ai.config import ConfigManager
    from tests.conftest import MockLedger
    from fava_ai.tools.base import BaseTool, ToolResult

    class AlwaysErrorTool(BaseTool):
        name = "error_tool"
        description = "Always errors"
        parameters = {"type": "object", "properties": {}}

        def execute(self, **kwargs):
            raise RuntimeError("intentional")

    provider = MockProvider([
        ChatResponse(tool_calls=[
            ToolCall(id="1", function=FunctionCall(
                name="error_tool", arguments="{}"
            ))
        ]),
        ChatResponse(content="Error handled gracefully."),
    ])

    cm = ConfigManager(None, {"provider": "mock"}, __import__("pathlib").Path("/tmp"))
    reg = ProviderRegistry(cm)
    reg.register("mock", provider)

    ledger = MockLedger([], {"operating_currency": ["USD"]})
    tool_reg = ToolRegistry()
    register_ledger_tools(tool_reg, ledger)
    tool_reg.register(AlwaysErrorTool())
    cb = ContextBuilder(ledger, tool_reg)

    agent = AgentRuntime(
        provider_registry=reg,
        tool_registry=tool_reg,
        context_builder=cb,
        config={"max_iterations": 3, "max_tool_calls": 5},
    )

    result = agent.run("Test", provider_name="mock")
    assert "Error handled" in result["content"]


def test_context_builder_with_kb_injection():
    from fava_ai.tools.registry import ToolRegistry
    from fava_ai.tools.builtin.ledger import register_ledger_tools
    from fava_ai.agent.context import ContextBuilder
    from fava_ai.knowledge.wiki import WikiManager
    from tests.conftest import MockLedger
    from pathlib import Path
    import tempfile

    with tempfile.TemporaryDirectory() as d:
        wiki = WikiManager(Path(d))
        wiki.write("merchants/test-merchant.md",
                   "# Test\nMonthly spending: $800.00 on utilities.",
                   {"title": "Test", "type": "merchant"})

        ledger = MockLedger([], {"operating_currency": ["USD"]})
        tool_reg = ToolRegistry()
        register_ledger_tools(tool_reg, ledger)
        cb = ContextBuilder(ledger, tool_reg, wiki)

        prompt = cb.build_system_prompt("tell me about utilities spending")
        assert "Knowledge Base Context" in prompt
        assert "Test" in prompt
        assert "Monthly spending" in prompt


def test_agent_no_provider():
    from fava_ai.agent.runtime import AgentRuntime
    from fava_ai.tools.registry import ToolRegistry
    from fava_ai.agent.context import ContextBuilder
    from fava_ai.models.registry import ProviderRegistry
    from fava_ai.config import ConfigManager
    from tests.conftest import MockLedger
    from pathlib import Path

    # Register a mock provider but with no default; require explicit provider_name
    import tempfile
    with tempfile.TemporaryDirectory() as d:
        cm = ConfigManager(None, {"provider": "mock"}, Path(d))
        reg = ProviderRegistry(cm)

        # Clear default providers to avoid Ollama connection attempt
        reg._providers.clear()

        ledger = MockLedger([], {"operating_currency": ["USD"]})
        tool_reg = ToolRegistry()
        cb = ContextBuilder(ledger, tool_reg)

        agent = AgentRuntime(
            provider_registry=reg,
            tool_registry=tool_reg,
            context_builder=cb,
        )

        with pytest.raises(RuntimeError, match="No provider"):
            agent.run("test")
