"""DeepSeek provider via litellm."""

from fava_ai.models.litellm_base import LiteLLMProvider


class DeepSeekProvider(LiteLLMProvider):
    model_prefix = "deepseek"

    def __init__(self, api_key: str = "", model: str = "deepseek-chat"):
        super().__init__(api_key=api_key, model=model)

    @property
    def provider_name(self) -> str:
        return "deepseek"

    def list_models(self) -> list[str]:
        return ["deepseek-chat", "deepseek-reasoner"]
