"""OpenAI provider via litellm."""

from fava_ai.models.litellm_base import LiteLLMProvider


class OpenAIProvider(LiteLLMProvider):
    model_prefix = "openai"

    @property
    def provider_name(self) -> str:
        return "openai"
