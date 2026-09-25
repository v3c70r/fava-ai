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
        # Grace budget for the final tool-less "wrap up" call after a limit.
        "wrap_up_seconds": 60,
    },
    "knowledge": {
        "auto_extract": True,
    },
    "tools": {
        # Loading arbitrary Python from .fava-ai/tools/ is opt-in: it executes
        # code from the ledger directory with the user's privileges.
        "external_enabled": False,
        # Filing a document by appending to a dedicated beancount file is
        # opt-in; the default is to return a paste-ready snippet only.
        "allow_ledger_writes": False,
        "ledger_writes_file": "documents.beancount",
    },
    "documents": {
        # Aggregate existing documents into a searchable local index.
        "enabled": False,
        "folders": [],
        "max_file_mb": 25,
        "max_pages": 50,
        "max_chars_per_doc": 200000,
        # Hybrid retrieval: ignore the dense ranking when even its best cosine
        # is below this (a weak embedder otherwise drags the fused result down).
        "hybrid_min_score": 0.2,
        # Optional OpenAI-compatible /v1/embeddings endpoint (phase 2).
        "embedding": {},
    },
}

#: The only provider implementation. Every vendor offers an OpenAI-compatible
#: endpoint, so a configured `base_url` + `api_key` + `model` is enough.
CANONICAL_PROVIDER = "openai_compat"

#: Accepted provider names. All resolve to the single OpenAI-compatible
#: implementation; the well-known vendors below also get a default base URL.
#: Any other name works too, as long as it supplies a `base_url` (e.g. a local
#: Ollama / llama.cpp / LM Studio / vLLM server).
PROVIDER_ALIASES: dict[str, str] = {
    "openai_compat": CANONICAL_PROVIDER,
    "openai": CANONICAL_PROVIDER,
    "anthropic": CANONICAL_PROVIDER,
    "deepseek": CANONICAL_PROVIDER,
    "google": CANONICAL_PROVIDER,
    "groq": CANONICAL_PROVIDER,
    "mistral": CANONICAL_PROVIDER,
    "xai": CANONICAL_PROVIDER,
    "together": CANONICAL_PROVIDER,
    "openrouter": CANONICAL_PROVIDER,
    "cerebras": CANONICAL_PROVIDER,
    "nvidia": CANONICAL_PROVIDER,
    "moonshotai": CANONICAL_PROVIDER,
    "fireworks": CANONICAL_PROVIDER,
    "baseten": CANONICAL_PROVIDER,
    "huggingface": CANONICAL_PROVIDER,
    "vercel-ai-gateway": CANONICAL_PROVIDER,
    "meta": CANONICAL_PROVIDER,
    "xiaomi": CANONICAL_PROVIDER,
}

#: Backwards-compatible name kept for validation/config tooling.
KNOWN_PROVIDERS = set(PROVIDER_ALIASES)

#: Default base URLs for well-known vendors (all OpenAI-compatible).
#: Local servers (Ollama, llama.cpp, LM Studio, vLLM, …) are not listed —
#: they are just `base_url`s, e.g. http://localhost:11434/v1.
KNOWN_BASE_URLS: dict[str, str] = {
    "openai": "https://api.openai.com/v1",
    "anthropic": "https://api.anthropic.com/v1",
    "deepseek": "https://api.deepseek.com/v1",
    "google": "https://generativelanguage.googleapis.com/v1beta/openai",
    "groq": "https://api.groq.com/openai/v1",
    "mistral": "https://api.mistral.ai/v1",
    "xai": "https://api.x.ai/v1",
    "together": "https://api.together.ai/v1",
    "openrouter": "https://openrouter.ai/api/v1",
    "cerebras": "https://api.cerebras.ai/v1",
    "nvidia": "https://integrate.api.nvidia.com/v1",
    "moonshotai": "https://api.moonshot.ai/v1",
    "fireworks": "https://api.fireworks.ai/inference/v1",
    "baseten": "https://inference.baseten.co/v1",
    "huggingface": "https://router.huggingface.co/v1",
    "vercel-ai-gateway": "https://ai-gateway.vercel.sh/v1",
    "meta": "https://api.meta.ai/v1",
    "xiaomi": "https://api.xiaomimimo.com/v1",
}

_ALLOWED_TOP_LEVEL = {"providers", "agent", "knowledge", "tools", "documents"}
_ALLOWED_PROVIDER_KEYS = {"type", "api_key", "base_url", "model", "timeout", "test_connection_method"}
#: Flat keys accepted directly in the beancount extension directive.
_FLAT_PROVIDER_KEYS = ("type", "api_key", "base_url", "model", "timeout", "test_connection_method")
_FLAT_AGENT_KEYS = (
    "max_iterations", "max_tool_calls", "timeout_seconds", "system_prompt",
    "max_context_tokens", "max_tool_result_chars", "retries", "max_tokens",
    "wrap_up_seconds",
)

_ALLOWED_AGENT_KEYS = set(_FLAT_AGENT_KEYS)
_ALLOWED_KNOWLEDGE_KEYS = {"auto_extract"}
_ALLOWED_TOOLS_KEYS = {"external_enabled", "allow_ledger_writes", "ledger_writes_file"}
_ALLOWED_DOCUMENTS_KEYS = {
    "enabled", "folders", "max_file_mb", "max_pages", "max_chars_per_doc",
    "hybrid_min_score", "embedding",
}
_DOCUMENT_INT_KEYS = ("max_file_mb", "max_pages", "max_chars_per_doc")


def _is_int(value) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def resolve_provider_type(name: str, cfg: dict) -> tuple[str | None, str | None]:
    """Resolve a provider entry to its canonical type.

    Returns ``(canonical_type, error)``; ``canonical_type`` is None on error.
    A name that is a known vendor (or a known ``type``) resolves directly. An
    arbitrary name (e.g. a local server) is treated as an OpenAI-compatible
    endpoint when it supplies a ``base_url``; otherwise it is an error (likely
    a typo).
    """
    ptype = cfg.get("type")
    if ptype is not None:
        canonical = PROVIDER_ALIASES.get(ptype)
        if canonical is None:
            return None, f"provider '{name}' has invalid type: '{ptype}'"
        return canonical, None
    canonical = PROVIDER_ALIASES.get(name)
    if canonical is not None:
        return canonical, None
    if cfg.get("base_url"):
        return CANONICAL_PROVIDER, None
    return None, f"unknown provider '{name}': set 'type' or 'base_url'"


def provider_base_url(name: str, cfg: dict) -> str:
    """Explicit base_url, else the well-known default for the provider name."""
    base_url = cfg.get("base_url")
    if base_url:
        return base_url
    return KNOWN_BASE_URLS.get(name, "")


def validate_config(data) -> list[str]:
    """Validate a config document (API writes and directive overlays).

    Returns a list of human-readable problems; empty means valid.
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
                _canonical, error = resolve_provider_type(name, cfg)
                if error:
                    errors.append(error)
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
            for key in _FLAT_AGENT_KEYS:
                if key == "system_prompt":
                    continue
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
            for key in ("external_enabled", "allow_ledger_writes"):
                if key in tools and not isinstance(tools[key], bool):
                    errors.append(f"'tools.{key}' must be a boolean")
            if "ledger_writes_file" in tools and not isinstance(tools["ledger_writes_file"], str):
                errors.append("'tools.ledger_writes_file' must be a string")

    documents = data.get("documents")
    if documents is not None:
        if not isinstance(documents, dict):
            errors.append("'documents' must be a mapping")
        else:
            extra = set(documents) - _ALLOWED_DOCUMENTS_KEYS
            if extra:
                errors.append(f"'documents' has unknown keys: {sorted(extra)}")
            if "enabled" in documents and not isinstance(documents["enabled"], bool):
                errors.append("'documents.enabled' must be a boolean")
            if "folders" in documents and not (
                isinstance(documents["folders"], list)
                and all(isinstance(f, str) for f in documents["folders"])
            ):
                errors.append("'documents.folders' must be a list of strings")
            for key in _DOCUMENT_INT_KEYS:
                if key in documents and (not _is_int(documents[key]) or documents[key] < 1):
                    errors.append(f"'documents.{key}' must be a positive integer")
            if "embedding" in documents and not isinstance(documents["embedding"], dict):
                errors.append("'documents.embedding' must be a mapping")
            if "hybrid_min_score" in documents:
                score = documents["hybrid_min_score"]
                if (
                    isinstance(score, bool)
                    or not isinstance(score, (int, float))
                    or not 0 <= score <= 1
                ):
                    errors.append(
                        "'documents.hybrid_min_score' must be a number between 0 and 1"
                    )

    return errors


class ConfigManager:
    """Resolve configuration from three layers.

    Precedence (lowest to highest): built-in defaults, the beancount
    ``fava-extension`` directive, then an optional ``.fava-ai/config.yaml``.

    The directive is the primary source: a single OpenAI-compatible endpoint
    can be declared entirely in the ledger. ``config.yaml`` is optional and
    only needed to override or to hold secrets out of the ledger.
    """

    def __init__(self, ledger, extension_config: dict | None, config_dir: Path):
        self._ledger = ledger
        # ``${ENV_VAR}`` references are resolved in the directive too, so
        # secrets can stay out of the (usually committed) ledger.
        self._extension_config = self._substitute_env(extension_config or {})
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

    # ── providers ─────────────────────────────────────────────────

    def get_provider_config(self) -> dict:
        """Merge provider entries from the directive and config.yaml.

        Supports three shapes:
        * flat single endpoint in the directive (``provider`` + ``base_url`` …)
        * a nested ``providers`` mapping in the directive
        * a nested ``providers`` mapping in config.yaml (highest precedence)
        """
        bc = self._extension_config
        providers: dict[str, dict] = {}

        name = bc.get("provider")
        if name:
            cfg = {k: bc[k] for k in _FLAT_PROVIDER_KEYS if k in bc}
            providers[name] = cfg

        bc_providers = bc.get("providers")
        if isinstance(bc_providers, dict):
            for provider_name, cfg in bc_providers.items():
                if isinstance(cfg, dict):
                    providers.setdefault(provider_name, {}).update(cfg)

        yaml_providers = self._yaml_config.get("providers", {})
        if isinstance(yaml_providers, dict):
            for provider_name, cfg in yaml_providers.items():
                if isinstance(cfg, dict):
                    providers.setdefault(provider_name, {}).update(cfg)
        return providers

    # ── agent / knowledge / tools ─────────────────────────────────

    def get_agent_config(self) -> dict:
        config = dict(DEFAULT_CONFIG["agent"])
        bc = self._extension_config
        # Flat keys (legacy directive form).
        for key in _FLAT_AGENT_KEYS:
            if key in bc:
                config[key] = bc[key]
        # Nested directive form.
        bc_agent = bc.get("agent")
        if isinstance(bc_agent, dict):
            config.update(bc_agent)
        # config.yaml overrides both.
        yaml_agent = self._yaml_config.get("agent", {})
        if isinstance(yaml_agent, dict):
            config.update(yaml_agent)
        return config

    def get_knowledge_config(self) -> dict:
        config = dict(DEFAULT_CONFIG["knowledge"])
        bc = self._extension_config
        if "auto_extract" in bc:
            config["auto_extract"] = bc["auto_extract"]
        if isinstance(bc.get("knowledge"), dict):
            config.update(bc["knowledge"])
        yaml_knowledge = self._yaml_config.get("knowledge", {})
        if isinstance(yaml_knowledge, dict):
            config.update(yaml_knowledge)
        return config

    def get_tools_config(self) -> dict:
        config = dict(DEFAULT_CONFIG["tools"])
        bc = self._extension_config
        if "external_enabled" in bc:
            config["external_enabled"] = bc["external_enabled"]
        if isinstance(bc.get("tools"), dict):
            config.update(bc["tools"])
        yaml_tools = self._yaml_config.get("tools", {})
        if isinstance(yaml_tools, dict):
            config.update(yaml_tools)
        return config

    def get_documents_config(self) -> dict:
        config = dict(DEFAULT_CONFIG["documents"])
        bc = self._extension_config
        if isinstance(bc.get("documents"), dict):
            config.update(bc["documents"])
        yaml_documents = self._yaml_config.get("documents", {})
        if isinstance(yaml_documents, dict):
            config.update(yaml_documents)
        return config

    def get(self, key: str, default=None):
        """Look up a dotted key, preferring config.yaml then the directive."""
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
