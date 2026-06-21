"""Unit tests for agent/ modules."""
import pytest

from fava_ai.agent.limits import ExecutionLimits, LimitExceeded


def test_execution_limits_defaults():
    limits = ExecutionLimits()
    assert limits.max_iterations == 10
    assert limits.max_tool_calls == 20
    assert limits.timeout_seconds == 120


def test_execution_limits_custom():
    limits = ExecutionLimits(max_iterations=5, max_tool_calls=10, timeout_seconds=30)
    assert limits.max_iterations == 5
    assert limits.max_tool_calls == 10
    assert limits.timeout_seconds == 30


def test_limit_exceeded():
    e = LimitExceeded("max_iterations")
    assert "max_iterations" in str(e)


def test_context_builder(sample_entries):
    from tests.conftest import MockLedger
    from fava_ai.tools.registry import ToolRegistry
    from fava_ai.tools.builtin.ledger import register_ledger_tools
    from fava_ai.agent.context import ContextBuilder

    ledger = MockLedger(sample_entries, {"operating_currency": ["USD"]})
    reg = ToolRegistry()
    register_ledger_tools(reg, ledger)
    cb = ContextBuilder(ledger, reg)

    prompt = cb.build_system_prompt()
    assert "USD" in prompt
    assert "run_bql" in prompt
    assert "list_accounts" in prompt
    assert "BQL queries" in prompt or "SELECT" in prompt


def test_context_builder_with_wiki(sample_entries, tmp_path):
    from tests.conftest import MockLedger
    from fava_ai.tools.registry import ToolRegistry
    from fava_ai.tools.builtin.ledger import register_ledger_tools
    from fava_ai.knowledge.wiki import WikiManager
    from fava_ai.agent.context import ContextBuilder

    wiki = WikiManager(tmp_path / "wiki")
    wiki.write(
        "merchants/test-merchant.md",
        "# Test Merchant\nSpent $500.00 on monthly subscription.",
        {"title": "Test Merchant", "type": "merchant"},
    )

    ledger = MockLedger([], {"operating_currency": ["USD"]})
    reg = ToolRegistry()
    register_ledger_tools(reg, ledger)
    cb = ContextBuilder(ledger, reg, wiki)

    prompt = cb.build_system_prompt("tell me about monthly subscription")
    assert "Knowledge Base Context" in prompt
    assert "Test Merchant" in prompt


def test_context_builder_no_wiki(sample_entries):
    from tests.conftest import MockLedger
    from fava_ai.tools.registry import ToolRegistry
    from fava_ai.tools.builtin.ledger import register_ledger_tools
    from fava_ai.agent.context import ContextBuilder

    ledger = MockLedger(sample_entries, {"operating_currency": ["USD"]})
    reg = ToolRegistry()
    register_ledger_tools(reg, ledger)
    cb = ContextBuilder(ledger, reg)

    prompt = cb.build_system_prompt("test")
    assert "Knowledge Base Context" not in prompt
