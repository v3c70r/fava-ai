from typing import Iterator

import litellm

from fava_ai.models.base import (
    BaseProvider,
    ChatResponse,
    Message,
    StreamChunk,
    ToolCall,
)


class OpenAICompatProvider(BaseProvider):
    """Generic OpenAI-compatible provider (vLLM, LM Studio, OpenRouter, etc.)"""

    def __init__(self, base_url: str = "", api_key: str = "", model: str = ""):
        self.base_url = base_url
        self.api_key = api_key
        self.default_model = model

    @property
    def provider_name(self) -> str:
        return "openai_compat"

    def _build_kwargs(self, messages: list[Message], tools=None, model=None, **kwargs):
        litellm_messages = [m.to_litellm() for m in messages]
        params = {
            "model": f"openai/{model or self.default_model}",
            "messages": litellm_messages,
            "api_base": self.base_url,
        }
        if self.api_key:
            params["api_key"] = self.api_key
        if tools:
            params["tools"] = tools
        params.update(kwargs)
        return params

    def chat(self, messages, tools=None, model=None, **kwargs):
        params = self._build_kwargs(messages, tools, model, **kwargs)
        response = litellm.completion(**params)
        choice = response.choices[0]
        message = choice.message

        tool_calls = None
        if message.tool_calls:
            tool_calls = [ToolCall.from_litellm(tc) for tc in message.tool_calls]

        usage = None
        if hasattr(response, "usage") and response.usage:
            usage = {
                "prompt_tokens": response.usage.prompt_tokens,
                "completion_tokens": response.usage.completion_tokens,
                "total_tokens": response.usage.total_tokens,
            }

        return ChatResponse(
            content=message.content,
            tool_calls=tool_calls,
            finish_reason=choice.finish_reason,
            usage=usage,
        )

    def chat_stream(self, messages, tools=None, model=None, **kwargs):
        params = self._build_kwargs(messages, tools, model, **kwargs)
        params["stream"] = True
        response = litellm.completion(**params)

        for chunk in response:
            choice = chunk.choices[0]
            delta = choice.delta
            chunk_tool_calls = None
            if delta.tool_calls:
                chunk_tool_calls = [ToolCall.from_litellm(tc) for tc in delta.tool_calls]

            yield StreamChunk(
                content=delta.content,
                tool_calls=chunk_tool_calls,
                finish_reason=choice.finish_reason,
            )

    def list_models(self) -> list[str]:
        return []

    def test_connection(self) -> bool:
        if not self.base_url:
            return False
        try:
            self.chat(
                [Message(role="user", content="hi")],
                model=self.default_model,
            )
            return True
        except Exception:
            return False
