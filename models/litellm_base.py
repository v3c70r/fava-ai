"""LiteLLMProvider — unified base for all litellm-backed providers.

Eliminates 5-way copy-paste of chat/chat_stream/usage extraction.
Subclasses only set model_prefix and optional list_models implementation.
"""

from abc import abstractmethod
from typing import Iterator

import litellm
from fava_ai.models.base import (
    BaseProvider,
    ChatResponse,
    FunctionCall,
    Message,
    StreamChunk,
    ToolCall,
)


class _ToolCallAccumulator:
    """Reassemble tool calls that arrive as fragments across stream chunks."""

    def __init__(self):
        self._by_index: dict[int, dict] = {}

    def add(self, delta_tool_calls) -> None:
        for tc in delta_tool_calls:
            index = getattr(tc, "index", None)
            if index is None:
                index = 0
            entry = self._by_index.setdefault(
                index, {"id": None, "name": None, "arguments": ""}
            )
            if getattr(tc, "id", None):
                entry["id"] = tc.id
            fn = getattr(tc, "function", None)
            if fn is not None:
                if getattr(fn, "name", None) and not entry["name"]:
                    entry["name"] = fn.name
                if getattr(fn, "arguments", None):
                    entry["arguments"] += fn.arguments

    def to_tool_calls(self) -> list[ToolCall]:
        tool_calls = []
        for index in sorted(self._by_index):
            entry = self._by_index[index]
            tool_calls.append(
                ToolCall(
                    id=entry["id"] or f"call_{index}",
                    function=FunctionCall(
                        name=entry["name"] or "",
                        arguments=entry["arguments"],
                    ),
                )
            )
        return tool_calls


class LiteLLMProvider(BaseProvider):
    """Base for all providers that use litellm.completion()."""

    model_prefix: str = ""
    default_model: str = ""

    def __init__(self, api_key: str = "", base_url: str = "", model: str = ""):
        self.api_key = api_key
        self.base_url = base_url
        if model:
            self.default_model = model

    @property
    @abstractmethod
    def provider_name(self) -> str:
        ...

    def _build_kwargs(self, messages: list[Message], tools=None, model=None, **kwargs):
        litellm_messages = [m.to_litellm() for m in messages]
        params = {
            "model": f"{self.model_prefix}/{model or self.default_model}",
            "messages": litellm_messages,
        }
        if self.api_key:
            params["api_key"] = self.api_key
        if self.base_url:
            params["api_base"] = self.base_url
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
        if "timeout" in kwargs:
            params["timeout"] = kwargs["timeout"]
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
            reasoning=getattr(message, "reasoning_content", None),
        )

    def chat_stream(
        self,
        messages: list[Message],
        tools: list[dict] | None = None,
        model: str | None = None,
        **kwargs,
    ) -> Iterator[StreamChunk]:
        """Stream a completion.

        Yields content deltas as they arrive, then a single final chunk that
        carries the fully-reassembled ``tool_calls`` (if any) and the finish
        reason. Tool-call fragments are accumulated by index because providers
        split them across many chunks.
        """
        params = self._build_kwargs(messages, tools, model, **kwargs)
        params["stream"] = True
        response = litellm.completion(**params)

        accumulator = _ToolCallAccumulator()
        finish_reason = None

        for chunk in response:
            if not getattr(chunk, "choices", None):
                continue
            choice = chunk.choices[0]
            delta = getattr(choice, "delta", None)
            if delta is not None and getattr(delta, "tool_calls", None):
                accumulator.add(delta.tool_calls)
            if getattr(choice, "finish_reason", None):
                finish_reason = choice.finish_reason
            if delta is None:
                continue
            reasoning = getattr(delta, "reasoning_content", None)
            if reasoning:
                yield StreamChunk(reasoning=reasoning)
            if delta.content:
                yield StreamChunk(content=delta.content)

        tool_calls = accumulator.to_tool_calls()
        yield StreamChunk(
            tool_calls=tool_calls or None,
            finish_reason=finish_reason,
        )

    def list_models(self) -> list[str]:
        return []

    def test_connection(self) -> bool:
        if not self.api_key and not self.base_url:
            return False
        try:
            # A 1-token completion is the most portable liveness check across
            # litellm providers. Providers with a cheaper endpoint override this.
            self.chat(
                [Message(role="user", content="ping")],
                max_tokens=1,
                timeout=10,
            )
            return True
        except Exception:
            return False
