"""Token counting and history-trimming tests."""

from fava_ai.agent.context import ContextBuilder
from fava_ai.agent.tokens import _approx_tokens, count_tokens
from fava_ai.models.base import FunctionCall, Message, ToolCall
from fava_ai.tools.registry import ToolRegistry

from tests.conftest import MockLedger


def _context_builder():
    ledger = MockLedger([], {"operating_currency": ["USD"]})
    return ContextBuilder(ledger, ToolRegistry())


def test_count_tokens_empty_is_zero():
    assert count_tokens([]) == 0


def test_count_tokens_positive_for_content():
    assert count_tokens([Message(role="user", content="hello world")]) > 0


def test_approx_tokens_scales_with_content():
    small = _approx_tokens([Message(role="user", content="x" * 40)])
    large = _approx_tokens([Message(role="user", content="x" * 4000)])
    assert large > small


def test_approx_tokens_counts_tool_call_arguments():
    with_tools = _approx_tokens([
        Message(
            role="assistant",
            tool_calls=[ToolCall(
                id="1",
                function=FunctionCall(name="run_bql", arguments="x" * 400),
            )],
        )
    ])
    without_tools = _approx_tokens([Message(role="assistant", content="x" * 400)])
    assert with_tools >= without_tools


def test_trim_history_noop_when_within_budget():
    cb = _context_builder()
    history = [Message(role="user", content=f"q{i}") for i in range(3)]
    kept, omitted = cb.trim_history(history, max_tokens=100_000)
    assert kept == history
    assert omitted == 0


def test_trim_history_drops_oldest_and_reports_count():
    cb = _context_builder()
    history = [Message(role="user", content=f"message number {i} " * 20) for i in range(50)]

    kept, omitted = cb.trim_history(history, max_tokens=200)

    assert omitted > 0
    assert len(kept) == len(history) - omitted
    # The most recent message is always kept.
    assert kept[-1].content == history[-1].content
    # Oldest messages were dropped.
    assert history[0].content not in [m.content for m in kept]


def test_trim_history_never_leaves_orphan_tool_result():
    cb = _context_builder()
    history = [
        Message(
            role="assistant",
            tool_calls=[ToolCall(
                id="1", function=FunctionCall(name="run_bql", arguments="{}")
            )],
        ),
        Message(role="tool", content="tool output", tool_call_id="1", name="run_bql"),
    ]

    kept, omitted = cb.trim_history(history, max_tokens=1)

    # The tool result cannot be kept without its assistant parent.
    assert all(m.role != "tool" for m in kept)
    assert omitted == 2


def test_trim_history_keeps_tool_pair_together():
    cb = _context_builder()
    history = [
        Message(role="user", content="old " * 5000),
        Message(
            role="assistant",
            tool_calls=[ToolCall(
                id="1", function=FunctionCall(name="run_bql", arguments="{}")
            )],
        ),
        Message(role="tool", content="result", tool_call_id="1", name="run_bql"),
    ]

    kept, _ = cb.trim_history(history, max_tokens=100)
    assert kept[0].role == "assistant"
    assert kept[1].role == "tool"
