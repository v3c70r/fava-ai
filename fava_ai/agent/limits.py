from dataclasses import dataclass


class LimitExceeded(Exception):
    pass


@dataclass
class ExecutionLimits:
    max_iterations: int = 10
    max_tool_calls: int = 20
    timeout_seconds: int = 120
