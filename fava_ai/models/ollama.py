"""Ollama provider via litellm."""

import requests

from fava_ai.models.litellm_base import LiteLLMProvider


class OllamaProvider(LiteLLMProvider):
    model_prefix = "ollama"

    def __init__(self, base_url: str = "http://localhost:11434", model: str = ""):
        super().__init__(api_key="", base_url=base_url, model=model)

    @property
    def provider_name(self) -> str:
        return "ollama"

    def list_models(self) -> list[str]:
        try:
            resp = requests.get(f"{self.base_url}/api/tags", timeout=5)
            if resp.status_code == 200:
                return [m["name"] for m in resp.json().get("models", [])]
        except Exception:
            pass
        return []

    def test_connection(self) -> bool:
        return len(self.list_models()) > 0
