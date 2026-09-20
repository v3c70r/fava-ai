from dataclasses import dataclass

from fava_ai.agent.errors import LimitExceeded

__all__ = ["ExecutionLimits", "LimitExceeded"]


@dataclass
class ExecutionLimits:
    max_iterations: int = 10
    max_tool_calls: int = 20
    timeout_seconds: int = 120
