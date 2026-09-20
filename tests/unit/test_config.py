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
    assert agent["timeout_seconds"] == 120


def test_config_manager_beancount_config():
    from tests.conftest import MockLedger
    ledger = MockLedger([], {"operating_currency": ["USD"]})
    bc = {"provider": "ollama", "model": "llama3", "max_iterations": 5}
    cm = ConfigManager(ledger, bc, Path("/tmp/fake"))
    agent = cm.get_agent_config()
    assert agent["max_iterations"] == 5
    assert agent["max_tool_calls"] == 20
    providers = cm.get_provider_config()
    assert "ollama" in providers
    assert providers["ollama"]["model"] == "llama3"


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
    bc = {"provider": "ollama", "model": "llama3"}
    cm = ConfigManager(ledger, bc, Path("/tmp/fake"))
    providers = cm.get_provider_config()
    assert providers["ollama"]["model"] == "llama3"


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
