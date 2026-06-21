import json
import time
import uuid

from fava_ai.models.base import Message
from fava_ai.agent.limits import ExecutionLimits, LimitExceeded


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

    def run(
        self,
        user_message: str,
        conversation_id: str | None = None,
        messages: list[Message] | None = None,
        provider_name: str | None = None,
    ) -> dict:
        provider = None
        if provider_name:
            provider = self._provider_registry.get(provider_name)
        if not provider:
            provider = self._provider_registry.get_default()
        if not provider:
            raise RuntimeError("No provider configured")

        conversation_id = conversation_id or str(uuid.uuid4())

        if messages is None:
            messages = []
            system_prompt = self._context_builder.build_system_prompt()
            messages.append(Message(role="system", content=system_prompt))

        messages.append(Message(role="user", content=user_message))

        tools = self._tool_registry.get_definitions()
        tool_call_count = 0
        start_time = time.time()

        trace_steps = []

        for iteration in range(self._limits.max_iterations):
            if time.time() - start_time > self._limits.timeout_seconds:
                raise LimitExceeded("timeout")

            trace_steps.append({
                "step_index": iteration,
                "step_type": "plan",
                "started_at": time.time(),
            })

            response = provider.chat(messages, tools=tools)

            trace_steps[-1]["completed_at"] = time.time()

            if response.has_tool_calls():
                messages.append(response.as_message())

                for tc in response.tool_calls:
                    tool_call_count += 1
                    if tool_call_count > self._limits.max_tool_calls:
                        raise LimitExceeded("max_tool_calls")

                    tool_name = tc.function.name

                    try:
                        result = self._tool_registry.execute(tc)
                        result_content = result.content
                        result_error = None
                    except Exception as e:
                        result_content = f"Tool error: {e}"
                        result_error = str(e)

                    trace_steps.append({
                        "step_index": iteration,
                        "step_type": "tool_call",
                        "tool_name": tool_name,
                        "tool_input": tc.function.arguments,
                        "tool_output": result_content[:500] if result_error is None else None,
                        "error": result_error,
                        "started_at": time.time(),
                        "completed_at": time.time(),
                    })

                    messages.append(Message(
                        role="tool",
                        content=result_content,
                        tool_call_id=tc.id,
                        name=tool_name,
                    ))

            elif response.content is not None:
                trace_steps.append({
                    "step_index": iteration,
                    "step_type": "synthesis",
                    "completed_at": time.time(),
                })

                return {
                    "conversation_id": conversation_id,
                    "content": response.content,
                    "messages": messages,
                    "usage": response.usage,
                    "trace": trace_steps,
                    "tool_call_count": tool_call_count,
                }

            else:
                break

        raise LimitExceeded("max_iterations")
