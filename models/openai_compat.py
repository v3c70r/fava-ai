"""Generic OpenAI-compatible provider (vLLM, LM Studio, OpenRouter, llama.cpp, etc.)"""

from fava_ai.models.litellm_base import LiteLLMProvider


class OpenAICompatProvider(LiteLLMProvider):
    model_prefix = "openai"

    @property
    def provider_name(self) -> str:
        return "openai_compat"
