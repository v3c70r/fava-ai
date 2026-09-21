import logging

from fava_ai.config import (
    CANONICAL_PROVIDER,
    provider_base_url,
    resolve_provider_type,
)
from fava_ai.models.base import BaseProvider
from fava_ai.models.openai_compat import OpenAICompatProvider

logger = logging.getLogger(__name__)


class ProviderRegistry:
    def __init__(self, config_manager):
        self._config_manager = config_manager
        self._providers: dict[str, BaseProvider] = {}
        self._connection_cache: dict[str, bool] = {}
        self._init_from_config()

    def _init_from_config(self):
        provider_config = self._config_manager.get_provider_config()
        for name, cfg in provider_config.items():
            canonical, error = resolve_provider_type(name, cfg)
            if error or canonical is None:
                logger.error("Ignoring provider '%s': %s", name, error)
                continue
            if canonical == CANONICAL_PROVIDER:
                provider: BaseProvider = OpenAICompatProvider(
                    base_url=provider_base_url(name, cfg),
                    api_key=cfg.get("api_key", ""),
                    model=cfg.get("model", ""),
                )
            else:  # pragma: no cover - only one canonical type today
                logger.error("Ignoring provider '%s': no implementation", name)
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

    def alias_of(self, provider: BaseProvider) -> str | None:
        """Return the configured alias for a provider instance (or None)."""
        for alias, candidate in self._providers.items():
            if candidate is provider:
                return alias
        return None
