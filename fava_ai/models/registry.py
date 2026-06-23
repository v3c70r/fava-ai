from fava_ai.models.base import BaseProvider
from fava_ai.models.ollama import OllamaProvider
from fava_ai.models.openai import OpenAIProvider
from fava_ai.models.anthropic import AnthropicProvider
from fava_ai.models.deepseek import DeepSeekProvider
from fava_ai.models.openai_compat import OpenAICompatProvider


class ProviderRegistry:
    def __init__(self, config_manager):
        self._config_manager = config_manager
        self._providers: dict[str, BaseProvider] = {}
        self._connection_cache: dict[str, bool] = {}
        self._init_from_config()

    def _init_from_config(self):
        provider_config = self._config_manager.get_provider_config()
        for name, cfg in provider_config.items():
            model = cfg.get("model", "")
            if name == "ollama":
                provider = OllamaProvider(
                    base_url=cfg.get("base_url", "http://localhost:11434"),
                    model=model,
                )
            elif name == "openai":
                provider = OpenAIProvider(
                    api_key=cfg.get("api_key", ""),
                    model=model,
                )
            elif name == "anthropic":
                provider = AnthropicProvider(
                    api_key=cfg.get("api_key", ""),
                    model=model,
                )
            elif name == "deepseek":
                provider = DeepSeekProvider(
                    api_key=cfg.get("api_key", ""),
                    model=model or "deepseek-chat",
                )
            elif name == "openai_compat":
                provider = OpenAICompatProvider(
                    base_url=cfg.get("base_url", ""),
                    api_key=cfg.get("api_key", ""),
                    model=model,
                )
            else:
                continue
            self._providers[name] = provider

        if not self._providers:
            self._providers["ollama"] = OllamaProvider()

    def get(self, name: str) -> BaseProvider | None:
        return self._providers.get(name)

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
