"""Security-focused tests: config validation, plugin gating, path safety."""

import json
import sys

import pytest
from fava_ai.config import validate_config
from fava_ai.knowledge.wiki import WikiManager
from fava_ai.tools.loader import load_external_tools

# ── config validation ─────────────────────────────────────────────


def test_validate_config_accepts_valid_document():
    errors = validate_config({
        "providers": {"openai": {"api_key": "sk-x", "model": "gpt-4o"}},
        "agent": {"max_iterations": 5, "system_prompt": "default"},
        "knowledge": {"auto_extract": True},
        "tools": {"external_enabled": False},
    })
    assert errors == []


def test_validate_config_allows_empty_document():
    assert validate_config({}) == []


def test_validate_config_rejects_unknown_top_level_key():
    errors = validate_config({"providers": {}, "evil": 1})
    assert any("unknown top-level" in e for e in errors)


def test_validate_config_rejects_unknown_provider():
    errors = validate_config({"providers": {"not-a-provider": {}}})
    assert any("unknown provider" in e for e in errors)


def test_validate_config_rejects_unknown_provider_key():
    errors = validate_config({"providers": {"openai": {"shell": "rm -rf /"}}})
    assert any("unknown keys" in e for e in errors)


def test_validate_config_rejects_bad_types():
    errors = validate_config({
        "agent": {"max_iterations": "lots"},
        "knowledge": {"auto_extract": "yes"},
        "tools": {"external_enabled": "yes"},
    })
    assert any("max_iterations" in e for e in errors)
    assert any("auto_extract" in e for e in errors)
    assert any("external_enabled" in e for e in errors)


def test_validate_config_rejects_non_mapping():
    assert validate_config([1, 2]) == ["config must be a mapping"]


# ── external plugin loader ────────────────────────────────────────

PLUGIN_SOURCE = """\
from fava_ai.tools.base import BaseTool, ToolResult


class PluginTool(BaseTool):
    @property
    def name(self):
        return "plugin_tool"

    @property
    def description(self):
        return "test plugin"

    @property
    def parameters(self):
        return {"type": "object", "properties": {}}

    def execute(self, **kwargs):
        return ToolResult(content="ok")


tools = [PluginTool()]
"""


def test_load_external_tools_does_not_touch_sys_path(tmp_path):
    tools_dir = tmp_path / "tools"
    tools_dir.mkdir()
    (tools_dir / "p.py").write_text(PLUGIN_SOURCE)

    before = list(sys.path)
    tools = load_external_tools(tools_dir)

    assert [t.name for t in tools] == ["plugin_tool"]
    assert sys.path == before  # no global path pollution


def test_load_external_tools_logs_broken_plugin(tmp_path, caplog):
    tools_dir = tmp_path / "tools"
    tools_dir.mkdir()
    (tools_dir / "broken.py").write_text("raise RuntimeError('bad import')\n")

    with caplog.at_level("ERROR"):
        tools = load_external_tools(tools_dir)

    assert tools == []
    assert any("broken.py" in r.message or "Failed to load" in r.message for r in caplog.records)


# ── external tool gating (extension init) ─────────────────────────


def _make_ext(tmp_path, external_enabled: bool):
    from fava_ai import FavaAI

    from tests.conftest import MockLedger

    beancount_file = tmp_path / "main.beancount"
    beancount_file.write_text("")
    ledger = MockLedger([], {"operating_currency": ["USD"]}, str(beancount_file))

    config_dir = tmp_path / ".fava-ai"
    config_dir.mkdir(parents=True, exist_ok=True)
    config_dir.joinpath("config.yaml").write_text(
        f"tools:\n  external_enabled: {'true' if external_enabled else 'false'}\n"
    )
    tools_dir = config_dir / "tools"
    tools_dir.mkdir()
    (tools_dir / "p.py").write_text(PLUGIN_SOURCE)

    return FavaAI(ledger, None)


def test_external_tools_disabled_by_default(tmp_path):
    ext = _make_ext(tmp_path, external_enabled=False)
    assert ext.tool_registry.get("plugin_tool") is None


def test_external_tools_enabled_when_configured(tmp_path):
    ext = _make_ext(tmp_path, external_enabled=True)
    assert ext.tool_registry.get("plugin_tool") is not None


# ── wiki path safety ──────────────────────────────────────────────


def test_safe_path_rejects_relative_traversal(tmp_path):
    wiki = WikiManager(tmp_path / "wiki")
    with pytest.raises(ValueError):
        wiki.read("../../etc/passwd")


def test_safe_path_rejects_absolute_path(tmp_path):
    wiki = WikiManager(tmp_path / "wiki")
    with pytest.raises(ValueError):
        wiki.read("/etc/passwd")


def test_safe_path_rejects_symlink_escape(tmp_path):
    wiki = WikiManager(tmp_path / "wiki")
    outside = tmp_path / "outside"
    outside.mkdir()
    link = wiki.wiki_dir / "link"
    try:
        link.symlink_to(outside)
    except OSError:
        pytest.skip("symlinks not supported")
    with pytest.raises(ValueError):
        wiki.read("link/evil.md")


def test_safe_path_allows_nested_inside(tmp_path):
    wiki = WikiManager(tmp_path / "wiki")
    assert wiki.read("notes/deep/page.md").content == ""


# ── wiki_write reserved paths ─────────────────────────────────────


def test_wiki_write_rejects_reserved_auto_generated_paths(tmp_path):
    from fava_ai.tools.builtin.wiki import WikiWriteTool

    wiki = WikiManager(tmp_path / "wiki")
    tool = WikiWriteTool(wiki)

    for path in ["overview.md", "index.md", "accounts/Foo.md", "merchants/Bar.md"]:
        result = tool.execute(path=path, content="clobber")
        assert "Refusing" in result.content, path
        assert not wiki.exists(path)


def test_wiki_write_allows_notes_and_forced_overwrite(tmp_path):
    from fava_ai.tools.builtin.wiki import WikiWriteTool

    wiki = WikiManager(tmp_path / "wiki")
    tool = WikiWriteTool(wiki)

    ok = tool.execute(path="notes/ok.md", content="hello")
    assert "written" in ok.content

    forced = tool.execute(path="accounts/Foo.md", content="manual", overwrite=True)
    assert "written" in forced.content
    assert wiki.exists("accounts/Foo.md")


def test_wiki_read_missing_page_reports_error(client=None):
    # WikiReadTool surfaces an error in metadata so provenance records it.
    import tempfile
    from pathlib import Path

    from fava_ai.tools.builtin.wiki import WikiReadTool

    with tempfile.TemporaryDirectory() as d:
        tool = WikiReadTool(WikiManager(Path(d)))
        result = tool.execute(path="nope.md")
        assert result.metadata["error"]
        assert json.loads(result.content)["error"]
