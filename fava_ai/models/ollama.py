import json
from typing import Iterator

import litellm

from fava_ai.models.base import (
    BaseProvider,
    ChatResponse,
    Message,
    StreamChunk,
    ToolCall,
    FunctionCall,
)


class OllamaProvider(BaseProvider):
    def __init__(self, base_url: str = "http://localhost:11434", model: str = ""):
        self.base_url = base_url
        self.default_model = model

    @property
    def provider_name(self) -> str:
        return "ollama"

    def _build_kwargs(self, messages: list[Message], tools=None, model=None, **kwargs):
        litellm_messages = [m.to_litellm() for m in messages]
        litellm_tools = tools if tools else None

        params = {
            "model": f"ollama/{model or self.default_model}",
            "messages": litellm_messages,
            "api_base": self.base_url,
        }
        if litellm_tools:
            params["tools"] = litellm_tools
        params.update(kwargs)
        return params

    def chat(
        self,
        messages: list[Message],
        tools: list[dict] | None = None,
        model: str | None = None,
        **kwargs,
    ) -> ChatResponse:
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

    def chat_stream(
        self,
        messages: list[Message],
        tools: list[dict] | None = None,
        model: str | None = None,
        **kwargs,
    ) -> Iterator[StreamChunk]:
        params = self._build_kwargs(messages, tools, model, **kwargs)
        params["stream"] = True

        response = litellm.completion(**params)

        for chunk in response:
            choice = chunk.choices[0]
            delta = choice.delta

            chunk_tool_calls = None
            if delta.tool_calls:
                chunk_tool_calls = [
                    ToolCall.from_litellm(tc) for tc in delta.tool_calls
                ]

            yield StreamChunk(
                content=delta.content,
                tool_calls=chunk_tool_calls,
                finish_reason=choice.finish_reason,
            )

    def list_models(self) -> list[str]:
        try:
            import requests
            resp = requests.get(f"{self.base_url}/api/tags", timeout=5)
            if resp.status_code == 200:
                models = resp.json().get("models", [])
                return [m["name"] for m in models]
            return []
        except Exception:
            return []

    def test_connection(self) -> bool:
        try:
            models = self.list_models()
            return len(models) > 0
        except Exception:
            return False
