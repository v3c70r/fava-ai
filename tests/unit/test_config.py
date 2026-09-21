"""Unit tests for config.py."""
import os
from pathlib import Path

import pytest
import yaml
from fava_ai.config import ConfigManager


def test_config_manager_defaults(tmp_dir):
    cm = ConfigManager(None, {}, tmp_dir)
    agent = cm.get_agent_config()
    assert agent["max_iterations"] == 10
    assert agent["max_tool_calls"] == 20
    assert agent["timeout_seconds"] == 300


def test_config_manager_beancount_config():
    from tests.conftest import MockLedger
    ledger = MockLedger([], {"operating_currency": ["USD"]})
    bc = {"provider": "openai", "model": "gpt-4o", "max_iterations": 5}
    cm = ConfigManager(ledger, bc, Path("/tmp/fake"))
    agent = cm.get_agent_config()
    assert agent["max_iterations"] == 5
    assert agent["max_tool_calls"] == 20
    providers = cm.get_provider_config()
    assert "openai" in providers
    assert providers["openai"]["model"] == "gpt-4o"


def test_config_manager_yaml_override(tmp_dir):
    yaml_path = tmp_dir / "config.yaml"
    yaml_path.write_text("agent:\n  max_iterations: 3\n  max_tool_calls: 5\n")
    cm = ConfigManager(None, {"max_iterations": 10}, tmp_dir)
    agent = cm.get_agent_config()
    assert agent["max_iterations"] == 3
    assert agent["max_tool_calls"] == 5


def test_config_manager_env_substitution(tmp_dir, monkeypatch):
    monkeypatch.setenv("TEST_KEY", "secret123")
    yaml_path = tmp_dir / "config.yaml"
    yaml_path.write_text("providers:\n  openai:\n    api_key: ${TEST_KEY}\n")
    cm = ConfigManager(None, {}, tmp_dir)
    providers = cm.get_provider_config()
    assert providers["openai"]["api_key"] == "secret123"


def test_config_manager_yaml_provider_merge():
    from tests.conftest import MockLedger
    ledger = MockLedger([], {"operating_currency": ["USD"]})
    bc = {"provider": "deepseek", "model": "deepseek-chat"}
    cm = ConfigManager(ledger, bc, Path("/tmp/fake"))
    providers = cm.get_provider_config()
    assert providers["deepseek"]["model"] == "deepseek-chat"


def test_config_manager_knowledge_config(tmp_dir):
    yaml_path = tmp_dir / "config.yaml"
    yaml_path.write_text("knowledge:\n  auto_extract: false\n")
    cm = ConfigManager(None, {}, tmp_dir)
    kc = cm.get_knowledge_config()
    assert kc["auto_extract"] is False


def test_config_manager_config_dir(tmp_dir):
    cm = ConfigManager(None, {}, tmp_dir)
    assert cm.config_dir == tmp_dir


def test_get_returns_present_falsy_values(tmp_dir):
    (tmp_dir / "config.yaml").write_text(
        "feature:\n  enabled: false\n  count: 0\n  name: ''\n"
    )
    cm = ConfigManager(None, {"feature.enabled": True}, tmp_dir)
    # Present-but-falsy values must win over the extension-config fallback.
    assert cm.get("feature.enabled") is False
    assert cm.get("feature.count") == 0
    assert cm.get("feature.name") == ""
    # Missing keys fall back to the extension config / default.
    assert cm.get("feature.missing", "fallback") == "fallback"
    assert cm.get("unknown", "d") == "d"


def test_resolve_provider_type_and_base_url():
    from fava_ai.config import provider_base_url, resolve_provider_type

    # Vendors are aliases for the single OpenAI-compatible implementation.
    assert resolve_provider_type("groq", {}) == ("openai_compat", None)
    assert resolve_provider_type("openai", {}) == ("openai_compat", None)
    assert resolve_provider_type(
        "local", {"base_url": "http://x/v1"}
    ) == ("openai_compat", None)

    # `ollama` is intentionally not special-cased: a local server is just a
    # base_url (see the README example).
    canonical, error = resolve_provider_type("ollama", {})
    assert canonical is None and error

    # Unknown name without type/base_url is an error (likely a typo).
    canonical, error = resolve_provider_type("mystery", {})
    assert canonical is None and error

    _canonical, error = resolve_provider_type("x", {"type": "nope"})
    assert error

    assert provider_base_url("groq", {}) == "https://api.groq.com/openai/v1"
    assert provider_base_url("openai", {}) == "https://api.openai.com/v1"
    assert provider_base_url("local", {"base_url": "http://x/v1"}) == "http://x/v1"
    assert provider_base_url("local", {}) == ""


def test_directive_nested_sections(tmp_dir):
    bc = {
        "provider": "local",
        "providers": {"local": {"base_url": "http://x/v1", "model": "m"}},
        "agent": {"timeout_seconds": 600, "max_iterations": 3},
        "knowledge": {"auto_extract": False},
        "tools": {"external_enabled": True},
    }
    cm = ConfigManager(None, bc, tmp_dir)

    assert cm.get_provider_config()["local"]["base_url"] == "http://x/v1"
    assert cm.get_agent_config()["timeout_seconds"] == 600
    assert cm.get_agent_config()["max_iterations"] == 3
    assert cm.get_knowledge_config()["auto_extract"] is False
    assert cm.get_tools_config()["external_enabled"] is True


def test_directive_flat_single_endpoint(tmp_dir):
    bc = {
        "provider": "local",
        "base_url": "http://localhost:8080/v1",
        "api_key": "k",
        "model": "m",
    }
    cm = ConfigManager(None, bc, tmp_dir)
    cfg = cm.get_provider_config()["local"]
    assert cfg["base_url"] == "http://localhost:8080/v1"
    assert cfg["api_key"] == "k"
    assert cfg["model"] == "m"


def test_directive_env_substitution(tmp_dir, monkeypatch):
    monkeypatch.setenv("MY_KEY", "secret")
    bc = {
        "provider": "local",
        "base_url": "http://x/v1",
        "api_key": "${MY_KEY}",
        "model": "m",
    }
    cm = ConfigManager(None, bc, tmp_dir)
    assert cm.get_provider_config()["local"]["api_key"] == "secret"


def test_yaml_overrides_directive(tmp_dir):
    (tmp_dir / "config.yaml").write_text(
        "agent:\n  max_iterations: 99\n"
        "providers:\n  local:\n    model: from-yaml\n"
    )
    cm = ConfigManager(None, {
        "provider": "local",
        "base_url": "http://x/v1",
        "model": "from-bc",
        "agent": {"max_iterations": 3},
    }, tmp_dir)

    assert cm.get_agent_config()["max_iterations"] == 99
    provider = cm.get_provider_config()["local"]
    assert provider["model"] == "from-yaml"
    # Non-overridden keys survive from the directive.
    assert provider["base_url"] == "http://x/v1"


def test_raw_provider_config_keeps_env_reference(tmp_dir, monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "resolved-value")
    (tmp_dir / "config.yaml").write_text(
        "providers:\n  openai:\n    api_key: ${OPENAI_API_KEY}\n"
    )
    cm = ConfigManager(None, {}, tmp_dir)
    # Resolved view...
    assert cm.get_provider_config()["openai"]["api_key"] == "resolved-value"
    # ...but the raw view preserves the reference for round-tripping.
    assert cm.raw_provider_config()["openai"]["api_key"] == "${OPENAI_API_KEY}"
