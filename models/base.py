from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Literal

import litellm

litellm.suppress_debug_info = True


@dataclass
class FunctionCall:
    name: str
    arguments: str


@dataclass
class ToolCall:
    id: str
    function: FunctionCall
    type: str = "function"

    @classmethod
    def from_litellm(cls, tc) -> "ToolCall":
        return cls(
            id=tc.id,
            type=getattr(tc, "type", "function"),
            function=FunctionCall(
                name=tc.function.name,
                arguments=tc.function.arguments,
            ),
        )

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "type": self.type,
            "function": {
                "name": self.function.name,
                "arguments": self.function.arguments,
            },
        }


@dataclass
class Message:
    role: Literal["system", "user", "assistant", "tool"]
    content: str | None = None
    tool_calls: list[ToolCall] | None = None
    tool_call_id: str | None = None
    name: str | None = None

    def to_litellm(self) -> dict:
        msg: dict = {"role": self.role}
        if self.content is not None:
            msg["content"] = self.content
        if self.tool_calls:
            msg["tool_calls"] = [tc.to_dict() for tc in self.tool_calls]
        if self.tool_call_id:
            msg["tool_call_id"] = self.tool_call_id
        if self.name:
            msg["name"] = self.name
        return msg


@dataclass
class ChatResponse:
    content: str | None = None
    tool_calls: list[ToolCall] | None = None
    finish_reason: str | None = None
    usage: dict | None = None

    def has_tool_calls(self) -> bool:
        return bool(self.tool_calls)

    def as_message(self) -> Message:
        return Message(
            role="assistant",
            content=self.content,
            tool_calls=self.tool_calls,
        )


@dataclass
class StreamChunk:
    content: str | None = None
    tool_calls: list[ToolCall] | None = None
    finish_reason: str | None = None


class BaseProvider(ABC):
    @property
    @abstractmethod
    def provider_name(self) -> str:
        ...

    @abstractmethod
    def chat(
        self,
        messages: list[Message],
        tools: list[dict] | None = None,
        model: str | None = None,
        **kwargs,
    ) -> ChatResponse:
        ...

    @abstractmethod
    def chat_stream(
        self,
        messages: list[Message],
        tools: list[dict] | None = None,
        model: str | None = None,
        **kwargs,
    ):
        ...

    @abstractmethod
    def list_models(self) -> list[str]:
        ...

    @abstractmethod
    def test_connection(self) -> bool:
        ...
