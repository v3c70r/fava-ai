"""OpenAI-compatible provider.

One implementation covers every supported vendor (OpenAI, DeepSeek, Ollama,
Anthropic, llama.cpp, LM Studio, vLLM, OpenRouter, …) because they all expose
an OpenAI-compatible ``/v1`` API. A provider is fully described by
``base_url`` + ``api_key`` + ``model``.
"""

import requests
from fava_ai.models.litellm_base import LiteLLMProvider


class OpenAICompatProvider(LiteLLMProvider):
    model_prefix = "openai"

    @property
    def provider_name(self) -> str:
        return "openai_compat"

    def _headers(self) -> dict:
        return {"Authorization": f"Bearer {self.api_key}"} if self.api_key else {}

    def list_models(self) -> list[str]:
        """List models via the OpenAI-compatible ``/models`` endpoint."""
        if not self.base_url:
            return []
        url = self.base_url.rstrip("/") + "/models"
        try:
            resp = requests.get(url, headers=self._headers(), timeout=5)
            if resp.status_code == 200:
                return [
                    m["id"] for m in resp.json().get("data", [])
                    if isinstance(m, dict) and m.get("id")
                ]
        except Exception:
            pass
        return []

    def test_connection(self) -> bool:
        # A model listing is a cheap liveness check when the endpoint supports
        # it; otherwise fall back to a 1-token completion.
        if self.base_url and self.list_models():
            return True
        return super().test_connection()
