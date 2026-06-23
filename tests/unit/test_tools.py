"""Unit tests for tools/ modules."""
import json
import pytest

from fava_ai.tools.base import ToolDefinition, ToolResult, ToolError, BaseTool
from fava_ai.tools.registry import ToolRegistry


class FakeTool(BaseTool):
    name = "fake_tool"
    description = "A fake tool for testing"
    parameters = {
        "type": "object",
        "properties": {"x": {"type": "integer"}},
        "required": ["x"],
    }

    def execute(self, x: int) -> ToolResult:
        return ToolResult(content=f"result: {x * 2}", metadata={"doubled": x * 2})


class ErrorTool(BaseTool):
    name = "error_tool"
    description = "Always errors"
    parameters = {"type": "object", "properties": {}}

    def execute(self) -> ToolResult:
        raise ValueError("intentional error")


class SlowTool(BaseTool):
    name = "slow_tool"
    description = "Slow tool"
    parameters = {"type": "object", "properties": {}}
    permission = "readonly"

    def execute(self) -> ToolResult:
        return ToolResult(content="done")


def test_tool_definition_to_openai_schema():
    td = ToolDefinition(
        name="test",
        description="test desc",
        parameters={"type": "object", "properties": {}},
    )
    schema = td.to_openai_schema()
    assert schema["type"] == "function"
    assert schema["function"]["name"] == "test"
    assert schema["function"]["description"] == "test desc"
    assert "parameters" in schema["function"]


def test_tool_result_defaults():
    tr = ToolResult(content="hello")
    assert tr.content == "hello"
    assert tr.metadata is None


def test_tool_error():
    e = ToolError("bad thing", tool_name="test")
    assert str(e) == "bad thing"
    assert e.tool_name == "test"


def test_registry_register_and_get():
    reg = ToolRegistry()
    tool = FakeTool()
    reg.register(tool)
    assert reg.get("fake_tool") is tool
    assert reg.get("nonexistent") is None


def test_registry_list_tools():
    reg = ToolRegistry()
    reg.register(FakeTool())
    reg.register(ErrorTool())
    tools = reg.list_tools()
    assert len(tools) == 2
    names = {t.name for t in tools}
    assert names == {"fake_tool", "error_tool"}


def test_registry_get_definitions():
    reg = ToolRegistry()
    reg.register(FakeTool())
    defs = reg.get_definitions()
    assert len(defs) == 1
    assert defs[0]["type"] == "function"
    assert defs[0]["function"]["name"] == "fake_tool"


def test_registry_execute():
    reg = ToolRegistry()
    reg.register(FakeTool())

    from fava_ai.models.base import ToolCall, FunctionCall
    tc = ToolCall(id="1", function=FunctionCall(name="fake_tool", arguments='{"x": 5}'))
    result = reg.execute(tc)
    assert result.content == "result: 10"
    assert result.metadata == {"doubled": 10}


def test_registry_execute_not_found():
    reg = ToolRegistry()
    from fava_ai.models.base import ToolCall, FunctionCall
    tc = ToolCall(id="1", function=FunctionCall(name="nonexistent", arguments="{}"))
    with pytest.raises(ToolError, match="Tool not found"):
        reg.execute(tc)


def test_registry_execute_bad_args():
    reg = ToolRegistry()
    reg.register(FakeTool())
    from fava_ai.models.base import ToolCall, FunctionCall
    tc = ToolCall(id="1", function=FunctionCall(name="fake_tool", arguments="not json"))
    with pytest.raises(ToolError, match="Invalid tool arguments"):
        reg.execute(tc)


def test_registry_unregister():
    reg = ToolRegistry()
    reg.register(FakeTool())
    reg.unregister("fake_tool")
    assert reg.get("fake_tool") is None


def test_base_tool_permission_default():
    tool = SlowTool()
    assert tool.permission == "readonly"


def test_wiki_write_tool(tmp_path):
    from fava_ai.knowledge.wiki import WikiManager
    from fava_ai.tools.builtin.wiki import WikiWriteTool

    wiki = WikiManager(tmp_path / "wiki")
    tool = WikiWriteTool(wiki)
    assert tool.name == "wiki_write"
    assert tool.permission == "write"

    result = tool.execute(path="notes/test.md", content="# Test\nHello", title="Test")
    assert "written" in result.content
    assert wiki.exists("notes/test.md")

    page = wiki.read("notes/test.md")
    assert page.content == "# Test\nHello"
    assert page.metadata["title"] == "Test"


def test_wiki_write_rejects_traversal(tmp_path):
    from fava_ai.knowledge.wiki import WikiManager
    from fava_ai.tools.builtin.wiki import WikiWriteTool

    wiki = WikiManager(tmp_path / "wiki")
    tool = WikiWriteTool(wiki)
    result = tool.execute(path="../../evil.md", content="hack", title="X")
    assert "Error" in result.content


def test_wiki_tools_registration_count():
    from fava_ai.tools.registry import ToolRegistry
    from fava_ai.knowledge.wiki import WikiManager
    from fava_ai.tools.builtin.wiki import register_wiki_tools
    import tempfile
    from pathlib import Path

    with tempfile.TemporaryDirectory() as d:
        wiki = WikiManager(Path(d))
        reg = ToolRegistry()
        register_wiki_tools(reg, wiki)
        tools = reg.list_tools()
        names = {t.name for t in tools}
        assert names == {"wiki_search", "wiki_read", "wiki_list", "wiki_write"}
