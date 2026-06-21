from typing import Iterator

import litellm

from fava_ai.models.base import (
    BaseProvider,
    ChatResponse,
    Message,
    StreamChunk,
    ToolCall,
)


class DeepSeekProvider(BaseProvider):
    def __init__(self, api_key: str = "", model: str = "deepseek-chat"):
        self.api_key = api_key
        self.default_model = model

    @property
    def provider_name(self) -> str:
        return "deepseek"

    def _build_kwargs(self, messages: list[Message], tools=None, model=None, **kwargs):
        litellm_messages = [m.to_litellm() for m in messages]
        params = {
            "model": f"deepseek/{model or self.default_model}",
            "messages": litellm_messages,
        }
        if self.api_key:
            params["api_key"] = self.api_key
        if tools:
            params["tools"] = tools
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
                chunk_tool_calls = [ToolCall.from_litellm(tc) for tc in delta.tool_calls]

            yield StreamChunk(
                content=delta.content,
                tool_calls=chunk_tool_calls,
                finish_reason=choice.finish_reason,
            )

    def list_models(self) -> list[str]:
        return ["deepseek-chat", "deepseek-reasoner"]

    def test_connection(self) -> bool:
        if not self.api_key:
            return False
        try:
            self.chat([Message(role="user", content="hi")])
            return True
        except Exception:
            return False
