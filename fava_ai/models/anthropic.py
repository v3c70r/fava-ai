"""Anthropic provider via litellm."""

from fava_ai.models.litellm_base import LiteLLMProvider


class AnthropicProvider(LiteLLMProvider):
    model_prefix = "anthropic"

    @property
    def provider_name(self) -> str:
        return "anthropic"
