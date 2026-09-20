import os
import re
from pathlib import Path

import yaml

DEFAULT_CONFIG: dict[str, dict] = {
    "agent": {
        "max_iterations": 10,
        "max_tool_calls": 20,
        # Slow local reasoning models on large ledgers can take minutes per answer.
        "timeout_seconds": 300,
        "system_prompt": "default",
        "max_context_tokens": 12000,
        "max_tool_result_chars": 8000,
        "retries": 2,
    },
    "knowledge": {
        "auto_extract": True,
    },
    "tools": {
        # Loading arbitrary Python from .fava-ai/tools/ is opt-in: it executes
        # code from the ledger directory with the user's privileges.
        "external_enabled": False,
    },
}

#: Providers the registry knows how to construct.
KNOWN_PROVIDERS = {"ollama", "openai", "anthropic", "deepseek", "openai_compat"}

_ALLOWED_TOP_LEVEL = {"providers", "agent", "knowledge", "tools"}
_ALLOWED_PROVIDER_KEYS = {"type", "api_key", "base_url", "model", "timeout", "test_connection_method"}
_ALLOWED_AGENT_KEYS = {
    "max_iterations", "max_tool_calls", "timeout_seconds", "system_prompt", "retries",
    "max_context_tokens", "max_tool_result_chars", "max_tokens",
}
_ALLOWED_KNOWLEDGE_KEYS = {"auto_extract"}
_ALLOWED_TOOLS_KEYS = {"external_enabled"}


def _is_int(value) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def validate_config(data) -> list[str]:
    """Validate a config document written via the API.

    Returns a list of human-readable problems; empty means valid. Kept
    intentionally small and dependency-free so the config file cannot be
    replaced with arbitrary or malformed content.
    """
    errors: list[str] = []
    if not isinstance(data, dict):
        return ["config must be a mapping"]

    unknown = set(data) - _ALLOWED_TOP_LEVEL
    if unknown:
        errors.append(f"unknown top-level keys: {sorted(unknown)}")

    providers = data.get("providers")
    if providers is not None:
        if not isinstance(providers, dict):
            errors.append("'providers' must be a mapping")
        else:
            for name, cfg in providers.items():
                if not isinstance(cfg, dict):
                    errors.append(f"provider '{name}' must be a mapping")
                    continue
                # Arbitrary aliases are allowed when an explicit 'type' names a
                # known provider implementation.
                ptype = cfg.get("type")
                if name in KNOWN_PROVIDERS:
                    if ptype is not None and ptype not in KNOWN_PROVIDERS:
                        errors.append(f"provider '{name}' has invalid type: '{ptype}'")
                elif ptype is None:
                    errors.append(
                        f"unknown provider '{name}': add a 'type' field "
                        f"(one of {sorted(KNOWN_PROVIDERS)})"
                    )
                elif ptype not in KNOWN_PROVIDERS:
                    errors.append(f"provider '{name}' has invalid type: '{ptype}'")

                extra = set(cfg) - _ALLOWED_PROVIDER_KEYS
                if extra:
                    errors.append(f"provider '{name}' has unknown keys: {sorted(extra)}")
                for key in ("type", "api_key", "base_url", "model"):
                    if key in cfg and not isinstance(cfg[key], str):
                        errors.append(f"provider '{name}.{key}' must be a string")

    agent = data.get("agent")
    if agent is not None:
        if not isinstance(agent, dict):
            errors.append("'agent' must be a mapping")
        else:
            extra = set(agent) - _ALLOWED_AGENT_KEYS
            if extra:
                errors.append(f"'agent' has unknown keys: {sorted(extra)}")
            for key in (
                "max_iterations", "max_tool_calls", "timeout_seconds", "retries",
                "max_context_tokens", "max_tool_result_chars", "max_tokens",
            ):
                if key in agent and (not _is_int(agent[key]) or agent[key] < 1):
                    errors.append(f"'agent.{key}' must be a positive integer")
            if "system_prompt" in agent and not isinstance(agent["system_prompt"], str):
                errors.append("'agent.system_prompt' must be a string")

    knowledge = data.get("knowledge")
    if knowledge is not None:
        if not isinstance(knowledge, dict):
            errors.append("'knowledge' must be a mapping")
        else:
            extra = set(knowledge) - _ALLOWED_KNOWLEDGE_KEYS
            if extra:
                errors.append(f"'knowledge' has unknown keys: {sorted(extra)}")
            if "auto_extract" in knowledge and not isinstance(knowledge["auto_extract"], bool):
                errors.append("'knowledge.auto_extract' must be a boolean")

    tools = data.get("tools")
    if tools is not None:
        if not isinstance(tools, dict):
            errors.append("'tools' must be a mapping")
        else:
            extra = set(tools) - _ALLOWED_TOOLS_KEYS
            if extra:
                errors.append(f"'tools' has unknown keys: {sorted(extra)}")
            if "external_enabled" in tools and not isinstance(tools["external_enabled"], bool):
                errors.append("'tools.external_enabled' must be a boolean")

    return errors


class ConfigManager:
    def __init__(self, ledger, extension_config: dict, config_dir: Path):
        self._ledger = ledger
        self._extension_config = extension_config
        self._config_dir = Path(config_dir)
        # Raw (un-substituted) config as read from disk. Kept so writes can
        # preserve ``${ENV_VAR}`` references instead of overwriting them with
        # resolved or masked values.
        self._raw_config: dict = {}
        self._yaml_config: dict = {}
        self._load_yaml()

    def _load_yaml(self):
        yaml_path = self._config_dir / "config.yaml"
        if yaml_path.exists():
            with open(yaml_path) as f:
                raw = yaml.safe_load(f) or {}
            if not isinstance(raw, dict):
                raw = {}
            self._raw_config = raw
            self._yaml_config = self._substitute_env(raw)
        else:
            self._raw_config = {}
            self._yaml_config = {}

    @staticmethod
    def _substitute_env(data):
        if isinstance(data, dict):
            return {k: ConfigManager._substitute_env(v) for k, v in data.items()}
        if isinstance(data, list):
            return [ConfigManager._substitute_env(v) for v in data]
        if isinstance(data, str):
            pattern = re.compile(r"\$\{(\w+)\}")
            return pattern.sub(
                lambda m: os.environ.get(m.group(1), m.group(0)), data
            )
        return data

    def raw_provider_config(self) -> dict:
        """Provider config exactly as written on disk (env refs unresolved)."""
        providers = self._raw_config.get("providers", {})
        return providers if isinstance(providers, dict) else {}

    def get_provider_config(self) -> dict:
        providers = {}
        bc = self._extension_config
        if bc.get("provider"):
            providers[bc["provider"]] = {"model": bc.get("model", "")}

        yaml_providers = self._yaml_config.get("providers", {})
        for name, cfg in yaml_providers.items():
            if name in providers:
                providers[name].update(cfg)
            else:
                providers[name] = dict(cfg)
        return providers

    def get_agent_config(self) -> dict:
        config = dict(DEFAULT_CONFIG["agent"])
        bc = self._extension_config
        for key in ["max_iterations", "max_tool_calls", "timeout_seconds"]:
            if key in bc:
                config[key] = bc[key]
        if "system_prompt" in bc:
            config["system_prompt"] = bc["system_prompt"]

        yaml_agent = self._yaml_config.get("agent", {})
        config.update(yaml_agent)
        return config

    def get_knowledge_config(self) -> dict:
        config = dict(DEFAULT_CONFIG["knowledge"])
        yaml_knowledge = self._yaml_config.get("knowledge", {})
        config.update(yaml_knowledge)
        return config

    def get_tools_config(self) -> dict:
        config = dict(DEFAULT_CONFIG["tools"])
        yaml_tools = self._yaml_config.get("tools", {})
        if isinstance(yaml_tools, dict):
            config.update(yaml_tools)
        return config

    def get(self, key: str, default=None):
        """Look up a dotted key in the YAML config, falling back to the
        beancount extension config.

        Unlike a naive ``dict.get`` chain, a present-but-falsy YAML value
        (``false``, ``0``, ``""``) is returned as-is instead of being treated
        as missing.
        """
        yaml_val: object = self._yaml_config
        found = True
        for part in key.split("."):
            if isinstance(yaml_val, dict) and part in yaml_val:
                yaml_val = yaml_val[part]
            else:
                found = False
                break
        if found:
            return yaml_val
        return self._extension_config.get(key, default)

    @property
    def config_dir(self) -> Path:
        return self._config_dir
