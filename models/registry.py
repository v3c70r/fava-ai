import logging

from fava_ai.config import KNOWN_PROVIDERS
from fava_ai.models.anthropic import AnthropicProvider
from fava_ai.models.base import BaseProvider
from fava_ai.models.deepseek import DeepSeekProvider
from fava_ai.models.ollama import OllamaProvider
from fava_ai.models.openai import OpenAIProvider
from fava_ai.models.openai_compat import OpenAICompatProvider

logger = logging.getLogger(__name__)


def _construct_provider(ptype: str, cfg: dict) -> BaseProvider | None:
    """Build a provider implementation from its type name and config."""
    model = cfg.get("model", "")
    if ptype == "ollama":
        return OllamaProvider(
            base_url=cfg.get("base_url", "http://localhost:11434"), model=model
        )
    if ptype == "openai":
        return OpenAIProvider(api_key=cfg.get("api_key", ""), model=model)
    if ptype == "anthropic":
        return AnthropicProvider(api_key=cfg.get("api_key", ""), model=model)
    if ptype == "deepseek":
        return DeepSeekProvider(
            api_key=cfg.get("api_key", ""), model=model or "deepseek-chat"
        )
    if ptype == "openai_compat":
        return OpenAICompatProvider(
            base_url=cfg.get("base_url", ""),
            api_key=cfg.get("api_key", ""),
            model=model,
        )
    return None


class ProviderRegistry:
    def __init__(self, config_manager):
        self._config_manager = config_manager
        self._providers: dict[str, BaseProvider] = {}
        self._connection_cache: dict[str, bool] = {}
        self._init_from_config()

    def _init_from_config(self):
        provider_config = self._config_manager.get_provider_config()
        for name, cfg in provider_config.items():
            # The name is an arbitrary alias; the implementation is chosen by
            # `type` when present, otherwise by the name itself if it is a
            # known provider.
            ptype = cfg.get("type") or (name if name in KNOWN_PROVIDERS else None)
            if ptype is None:
                logger.error(
                    "Ignoring provider '%s': unknown name and no 'type' field "
                    "(known types: %s)",
                    name, ", ".join(sorted(KNOWN_PROVIDERS)),
                )
                continue
            provider = _construct_provider(ptype, cfg)
            if provider is None:
                logger.error(
                    "Ignoring provider '%s': unsupported type '%s'", name, ptype
                )
                continue
            self._providers[name] = provider

    def get(self, name: str) -> BaseProvider | None:
        return self._providers.get(name)

    def invalidate(self, name: str | None = None):
        """Drop cached connection status, for one provider or all of them."""
        if name is None:
            self._connection_cache.clear()
        else:
            self._connection_cache.pop(name, None)

    def set_connection(self, name: str, connected: bool) -> None:
        """Record a freshly observed connection status for a provider."""
        self._connection_cache[name] = bool(connected)

    def get_default(self) -> BaseProvider | None:
        bc = self._config_manager._extension_config
        default_name = bc.get("provider", "ollama")
        return self.get(default_name) or (list(self._providers.values())[0] if self._providers else None)

    def list_providers(self) -> list[dict]:
        bc = self._config_manager._extension_config
        default_name = bc.get("provider", "ollama")
        result = []
        for name, provider in self._providers.items():
            connected = self._connection_cache.get(name)
            if connected is None:
                try:
                    connected = provider.test_connection()
                except Exception:
                    connected = False
                self._connection_cache[name] = connected
            result.append({
                "name": name,
                "is_default": name == default_name,
                "connected": connected,
            })
        return result

    def register(self, name: str, provider: BaseProvider):
        self._providers[name] = provider
