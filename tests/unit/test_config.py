"""Unit tests for config.py."""
import os
import yaml
import pytest
from pathlib import Path

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
