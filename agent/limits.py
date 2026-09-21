from dataclasses import dataclass

from fava_ai.agent.errors import LimitExceeded

__all__ = ["ExecutionLimits", "LimitExceeded"]


@dataclass
class ExecutionLimits:
    max_iterations: int = 10
    max_tool_calls: int = 20
    timeout_seconds: int = 300
    max_context_tokens: int = 12000
    max_tool_result_chars: int = 8000
    retries: int = 2
    #: Optional cap on generated tokens per provider call (None = provider default).
    max_tokens: int | None = None
    #: Grace budget for the final tool-less "wrap up" call after a limit is hit.
    wrap_up_seconds: int = 60
