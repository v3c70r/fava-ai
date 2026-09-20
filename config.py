import os
import re
from pathlib import Path

import yaml

DEFAULT_CONFIG: dict[str, dict] = {
    "agent": {
        "max_iterations": 10,
        "max_tool_calls": 20,
        "timeout_seconds": 120,
        "system_prompt": "default",
    },
    "knowledge": {
        "auto_extract": True,
    },
}


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
