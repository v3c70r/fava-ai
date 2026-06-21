"""Unit tests for prompts/ and provenance/ modules."""
import pytest
from pathlib import Path

from fava_ai.prompts.registry import PromptRegistry
from fava_ai.provenance.tracker import ExecutionTracker, ProvenanceStep


def test_prompt_registry_builtins():
    reg = PromptRegistry()
    prompts = reg.list_prompts()
    ids = {p["id"] for p in prompts}
    assert "default" in ids
    assert "monthly_review" in ids
    assert "investment_review" in ids


def test_prompt_registry_get():
    reg = PromptRegistry()
    p = reg.get("monthly_review")
    assert p is not None
    assert p["name"] == "Monthly Review"
    assert "monthly" in p["content"].lower()


def test_prompt_registry_get_default():
    reg = PromptRegistry()
    p = reg.get("nonexistent")
    assert p is None


def test_prompt_registry_search():
    reg = PromptRegistry()
    results = reg.search("investment")
    assert len(results) >= 1
    assert results[0]["id"] == "investment_review"


def test_prompt_registry_get_system_prompt():
    reg = PromptRegistry()
    prompt = reg.get_system_prompt("monthly_review")
    assert "financial review" in prompt.lower()


def test_prompt_registry_default_system_prompt():
    reg = PromptRegistry()
    prompt = reg.get_system_prompt()
    assert len(prompt) > 0


def test_prompt_registry_user_prompts(tmp_path):
    prompts_dir = tmp_path / "prompts"
    prompts_dir.mkdir()
    (prompts_dir / "custom.yaml").write_text(
        "name: Custom Review\ndescription: My custom review\ncontent: Do a custom analysis\ncategory: user\n"
    )

    reg = PromptRegistry(tmp_path)
    assert reg.get("custom") is not None
    assert reg.get("custom")["name"] == "Custom Review"


def test_provenance_tracker_init():
    tracker = ExecutionTracker()
    assert tracker.total_tool_calls == 0
    assert tracker.total_bql_queries == 0
    assert tracker.total_wiki_lookups == 0
    assert len(tracker.steps) == 0


def test_provenance_tracker_record_plan():
    tracker = ExecutionTracker()
    tracker.record_plan(0)
    assert len(tracker.steps) == 1
    assert tracker.steps[0].step_type == "plan"
    assert tracker.steps[0].step_index == 0


def test_provenance_tracker_record_tool_call():
    tracker = ExecutionTracker()
    tracker.record_tool_call(
        iteration=0,
        tool_name="run_bql",
        tool_input="SELECT *",
        tool_output='{"rows": 5}',
    )
    assert tracker.total_tool_calls == 1
    assert tracker.total_bql_queries == 1
    step = tracker.steps[0]
    assert step.tool_name == "run_bql"
    assert step.bql_query == "SELECT *"


def test_provenance_tracker_wiki_tracking():
    tracker = ExecutionTracker()
    tracker.record_tool_call(0, "wiki_search", "q=test", "3 results")
    tracker.record_tool_call(0, "wiki_read", "path=x", "content")
    assert tracker.total_tool_calls == 2
    assert tracker.total_wiki_lookups == 2


def test_provenance_tracker_record_synthesis():
    tracker = ExecutionTracker()
    tracker.record_synthesis(0)
    assert len(tracker.steps) == 1
    assert tracker.steps[0].step_type == "synthesis"


def test_provenance_tracker_to_dict():
    tracker = ExecutionTracker()
    tracker.record_plan(0)
    tracker.record_tool_call(0, "ledger_info", "{}", '{"currencies":["USD"]}')
    tracker.record_synthesis(0)

    d = tracker.to_dict()
    assert "tracker_id" in d
    assert d["total_steps"] == 3
    assert d["total_tool_calls"] == 1
    assert "duration_seconds" in d
    assert len(d["steps"]) == 3


def test_provenance_tracker_summary():
    tracker = ExecutionTracker()
    tracker.record_tool_call(0, "ledger_info", "{}", "result")
    tracker.record_tool_call(0, "run_bql", "SELECT *", "rows")
    tracker.record_tool_call(0, "wiki_search", "q", "pages")

    summary = tracker.provenance_summary()
    assert "ledger_info" in summary
    assert "run_bql" in summary
    assert "wiki_search" in summary
    assert "**Tool calls:** 3" in summary
    assert "BQL queries run" in summary
    assert "Wiki lookups" in summary


def test_provenance_step_to_dict():
    step = ProvenanceStep(
        step_index=0,
        step_type="tool_call",
        tool_name="run_bql",
        tool_input="SELECT *",
        bql_query="SELECT *",
        error=None,
    )
    d = step.to_dict()
    assert d["step_type"] == "tool_call"
    assert d["tool_name"] == "run_bql"
    assert d["bql_query"] == "SELECT *"


def test_provenance_tracker_with_error():
    tracker = ExecutionTracker()
    tracker.record_tool_call(
        iteration=0,
        tool_name="run_bql",
        tool_input="BAD QUERY",
        tool_output="",
        error="Syntax error",
    )
    assert tracker.steps[0].error == "Syntax error"
