"""AgentRuntime — orchestration loop with provenance tracking.

Two entry points share the same tool-execution logic:

* :meth:`run` — blocking, one ``ChatResponse`` per iteration.
* :meth:`run_stream` — a generator that yields UI events and ends with a
  ``done`` event carrying the same result shape as :meth:`run`.
"""

import time
import uuid

from fava_ai.agent.errors import (
    EmptyResponseError,
    LimitExceeded,
    NoProviderError,
    ProviderError,
)
from fava_ai.agent.limits import ExecutionLimits
from fava_ai.models.base import Message
from fava_ai.provenance.tracker import ExecutionTracker


class AgentRuntime:
    def __init__(
        self,
        provider_registry,
        tool_registry,
        context_builder,
        config: dict | None = None,
    ):
        self._provider_registry = provider_registry
        self._tool_registry = tool_registry
        self._context_builder = context_builder
        agent_config = config or {}
        self._limits = ExecutionLimits(
            max_iterations=agent_config.get("max_iterations", 10),
            max_tool_calls=agent_config.get("max_tool_calls", 20),
            timeout_seconds=agent_config.get("timeout_seconds", 120),
        )

    # ── setup helpers ─────────────────────────────────────────────

    def _resolve_provider(self, provider_name: str | None):
        if provider_name:
            provider = self._provider_registry.get(provider_name)
            if provider is None:
                raise NoProviderError(
                    f"Unknown provider '{provider_name}'. "
                    "Check the 'providers' section of .fava-ai/config.yaml."
                )
            return provider
        provider = self._provider_registry.get_default()
        if provider is None:
            raise NoProviderError(
                "No LLM provider configured. Add one to .fava-ai/config.yaml "
                "(see README for examples)."
            )
        return provider

    def _prepare(self, messages, user_message, prompt_id):
        """Insert the system prompt and the user turn into the message list."""
        if messages is None:
            messages = []
        system_prompt = self._context_builder.build_system_prompt(
            user_message, prompt_id=prompt_id
        )
        messages.insert(0, Message(role="system", content=system_prompt))
        existing_count = len(messages)
        messages.append(Message(role="user", content=user_message))
        return messages, existing_count

    def _result(self, conversation_id, content, messages, existing_count,
                tracker, usage, tool_call_count):
        return {
            "conversation_id": conversation_id,
            "content": content,
            "messages": messages,
            "new_messages": messages[existing_count:],
            "usage": usage,
            "provenance": tracker.to_dict(),
            "provenance_summary": tracker.provenance_summary(),
            "tool_call_count": tool_call_count,
        }

    # ── tool execution ────────────────────────────────────────────

    def _run_tool_call(self, tc, iteration, tracker) -> tuple[str, str | None, str]:
        """Execute one tool call, record provenance, return (content, error, name)."""
        tool_name = tc.function.name
        try:
            result = self._tool_registry.execute(tc)
            content = result.content
            # Tools report handled failures via metadata["error"] instead of
            # raising (e.g. BQL syntax errors).
            error = None
            if result.metadata and result.metadata.get("error"):
                error = str(result.metadata["error"])
        except Exception as e:  # noqa: BLE001 - surface tool errors to the model
            content = f"Tool error: {e}"
            error = str(e)

        tracker.record_tool_call(
            iteration=iteration,
            tool_name=tool_name,
            tool_input=tc.function.arguments,
            tool_output=content,
            error=error,
        )
        return content, error, tool_name

    def _call_provider(self, provider, messages, tools, remaining, model):
        """Call the provider, translating unexpected failures into ProviderError."""
        try:
            try:
                return provider.chat(
                    messages, tools=tools, model=model, timeout=remaining
                )
            except TypeError:
                # Provider doesn't accept a timeout kwarg.
                return provider.chat(messages, tools=tools, model=model)
        except (LimitExceeded, ProviderError):
            raise
        except Exception as e:  # noqa: BLE001 - normalise provider failures
            raise ProviderError(f"Provider request failed: {e}") from e

    # ── blocking loop ─────────────────────────────────────────────

    def run(
        self,
        user_message: str,
        conversation_id: str | None = None,
        messages: list[Message] | None = None,
        provider_name: str | None = None,
        model: str | None = None,
        prompt_id: str | None = None,
    ) -> dict:
        provider = self._resolve_provider(provider_name)
        conversation_id = conversation_id or str(uuid.uuid4())

        tracker = ExecutionTracker()
        messages, existing_count = self._prepare(messages, user_message, prompt_id)

        tools = self._tool_registry.get_definitions()
        tool_call_count = 0
        start_time = time.time()

        for iteration in range(self._limits.max_iterations):
            remaining = self._limits.timeout_seconds - (time.time() - start_time)
            if remaining <= 0:
                raise LimitExceeded("timeout")

            tracker.record_plan(iteration)
            response = self._call_provider(provider, messages, tools, remaining, model)

            if response.has_tool_calls():
                messages.append(response.as_message())
                for tc in response.tool_calls:
                    tool_call_count += 1
                    if tool_call_count > self._limits.max_tool_calls:
                        raise LimitExceeded("max_tool_calls")
                    content, _error, tool_name = self._run_tool_call(tc, iteration, tracker)
                    messages.append(Message(
                        role="tool", content=content,
                        tool_call_id=tc.id, name=tool_name,
                    ))

            elif response.content:
                tracker.record_synthesis(iteration)
                messages.append(response.as_message())
                return self._result(
                    conversation_id, response.content, messages, existing_count,
                    tracker, response.usage, tool_call_count,
                )

            else:
                raise EmptyResponseError(
                    "The model returned an empty response "
                    "(no content and no tool calls)."
                )

        raise LimitExceeded("max_iterations")

    # ── streaming loop ────────────────────────────────────────────

    def run_stream(
        self,
        user_message: str,
        conversation_id: str | None = None,
        messages: list[Message] | None = None,
        provider_name: str | None = None,
        model: str | None = None,
        prompt_id: str | None = None,
    ):
        """Yield UI events, ending with ``{"type": "done", "result": {...}}``.

        Event types: ``content_delta``, ``tool_call_start``, ``tool_call``,
        ``done``. Errors propagate as :class:`AgentError` for the caller to map.
        """
        provider = self._resolve_provider(provider_name)
        conversation_id = conversation_id or str(uuid.uuid4())

        tracker = ExecutionTracker()
        messages, existing_count = self._prepare(messages, user_message, prompt_id)

        tools = self._tool_registry.get_definitions()
        tool_call_count = 0
        start_time = time.time()

        for iteration in range(self._limits.max_iterations):
            if self._limits.timeout_seconds - (time.time() - start_time) <= 0:
                raise LimitExceeded("timeout")

            tracker.record_plan(iteration)

            content_parts: list[str] = []
            final_tool_calls = None
            try:
                stream = provider.chat_stream(messages, tools=tools, model=model)
                for chunk in stream:
                    if self._limits.timeout_seconds - (time.time() - start_time) <= 0:
                        raise LimitExceeded("timeout")
                    if chunk.content:
                        content_parts.append(chunk.content)
                        yield {"type": "content_delta", "content": chunk.content}
                    if chunk.tool_calls:
                        final_tool_calls = chunk.tool_calls
            except (LimitExceeded, ProviderError):
                raise
            except Exception as e:  # noqa: BLE001 - normalise provider failures
                raise ProviderError(f"Provider stream failed: {e}") from e

            if final_tool_calls:
                messages.append(Message(
                    role="assistant",
                    content="".join(content_parts) or None,
                    tool_calls=final_tool_calls,
                ))
                for tc in final_tool_calls:
                    tool_call_count += 1
                    if tool_call_count > self._limits.max_tool_calls:
                        raise LimitExceeded("max_tool_calls")

                    yield {"type": "tool_call_start", "tool_name": tc.function.name}
                    content, _error, tool_name = self._run_tool_call(
                        tc, iteration, tracker
                    )
                    messages.append(Message(
                        role="tool", content=content,
                        tool_call_id=tc.id, name=tool_name,
                    ))
                    yield {
                        "type": "tool_call",
                        "step": tracker.steps[-1].to_dict(),
                    }

            elif content_parts:
                content = "".join(content_parts)
                messages.append(Message(role="assistant", content=content))
                tracker.record_synthesis(iteration)
                result = self._result(
                    conversation_id, content, messages, existing_count,
                    tracker, None, tool_call_count,
                )
                yield {"type": "done", "result": result}
                return

            else:
                raise EmptyResponseError(
                    "The model returned an empty response "
                    "(no content and no tool calls)."
                )

        raise LimitExceeded("max_iterations")
