"""Agent error taxonomy.

Every error raised by the agent runtime derives from :class:`AgentError` and
declares the HTTP status the extension layer should return. This keeps the
endpoint layer free of ad-hoc exception mapping.
"""


class AgentError(Exception):
    """Base class for all agent runtime errors."""

    #: HTTP status the extension API should return for this error.
    http_status: int = 500

    def __init__(self, message: str = ""):
        super().__init__(message)
        self.message = message


class NoProviderError(AgentError):
    """No LLM provider is configured (or the requested one is unknown)."""

    http_status = 503


class ProviderError(AgentError):
    """The configured provider failed to answer the request."""

    http_status = 502


class EmptyResponseError(AgentError):
    """The model returned neither content nor tool calls."""

    http_status = 502


class ToolLoopError(AgentError):
    """The tool-calling loop could not make progress."""

    http_status = 500


class LimitExceeded(AgentError):
    """An execution limit (iterations, tool calls, timeout) was hit."""

    http_status = 429
