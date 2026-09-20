"""Fixtures for endpoint-level (Flask test client) tests.

Fava registers extension endpoints by pulling unbound functions out of
``FavaExtensionBase.endpoints`` and calling them with the extension instance.
We reproduce that wiring here without needing a full Fava app, so every
endpoint can be exercised in-process.
"""

import pytest
from flask import Flask


@pytest.fixture
def ledger(sample_entries, tmp_path):
    from tests.conftest import MockLedger

    beancount_file = tmp_path / "main.beancount"
    beancount_file.write_text("")
    return MockLedger(
        sample_entries, {"operating_currency": ["USD"]}, str(beancount_file)
    )


@pytest.fixture
def ext(ledger):
    """A fully-initialised FavaAI extension backed by a temporary config dir."""
    from fava_ai import FavaAI

    return FavaAI(ledger, None)


@pytest.fixture
def client(ext):
    app = Flask(__name__)
    app.config["TESTING"] = True

    # (endpoint_name, method) -> unbound function, mirroring Fava's registration.
    for (name, method), func in ext.endpoints.items():
        app.add_url_rule(
            f"/{name}",
            endpoint=f"{name}_{method.lower()}",
            view_func=(lambda _f=func, _e=ext: _f(_e)),
            methods=[method],
        )

    with app.test_client() as c:
        yield c


class StubRuntime:
    """Drop-in replacement for AgentRuntime returning a canned result/error."""

    def __init__(self, result=None, error=None, events=None):
        self._result = result
        self._error = error
        self._events = events
        self.calls = []

    def run(self, **kwargs):
        self.calls.append(kwargs)
        if self._error is not None:
            raise self._error
        return self._result

    def run_stream(self, **kwargs):
        self.calls.append(kwargs)
        if self._error is not None:
            raise self._error
        if self._events is not None:
            yield from self._events
            return
        result = self._result if self._result is not None else make_result()
        yield {"type": "content_delta", "content": result["content"]}
        for step in result.get("provenance", {}).get("steps", []):
            if step.get("step_type") == "tool_call":
                yield {"type": "tool_call", "step": step}
        yield {"type": "done", "result": result}


def make_result(
    conversation_id="conv-1",
    content="The answer is 42.",
    user_message="question",
    tool_name=None,
    error=None,
):
    """Build a result dict shaped like AgentRuntime.run()."""
    from fava_ai.models.base import Message

    steps = [{"step_index": 0, "step_type": "plan"}]
    if tool_name:
        steps.append({
            "step_index": 0,
            "step_type": "tool_call",
            "tool_name": tool_name,
            "tool_input": "{}",
            "tool_output": "{}",
            "error": error,
        })
    steps.append({"step_index": 1, "step_type": "synthesis"})

    messages = [
        Message(role="system", content="sys"),
        Message(role="user", content=user_message),
        Message(role="assistant", content=content),
    ]
    return {
        "conversation_id": conversation_id,
        "content": content,
        "messages": messages,
        "new_messages": messages[1:],
        "usage": {"total_tokens": 10},
        "provenance": {"total_steps": len(steps), "steps": steps},
        "provenance_summary": "**Tool calls:** 1",
        "tool_call_count": 1 if tool_name else 0,
    }
