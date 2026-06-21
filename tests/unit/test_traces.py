"""Unit tests for traces storage."""
import pytest

from fava_ai.storage.database import Database
from fava_ai.storage.traces import save_trace, get_traces


@pytest.fixture
def db(tmp_path):
    db_path = tmp_path / "test.db"
    d = Database(db_path)
    d.initialize()
    return d


def test_save_and_get_traces(db):
    # Create conversation first for FK constraint
    db.conn.execute(
        "INSERT INTO conversations (id, provider, model) VALUES (?, ?, ?)",
        ("conv_1", "ollama", "llama3"),
    )
    db.conn.commit()

    db.conn.execute(
        "INSERT INTO messages (id, conversation_id, role, content) VALUES (?, ?, ?, ?)",
        ("msg_1", "conv_1", "user", "test"),
    )
    db.conn.commit()

    steps = [
        {"step_index": 0, "step_type": "plan", "tool_name": None},
        {
            "step_index": 0,
            "step_type": "tool_call",
            "tool_name": "ledger_info",
            "tool_input": "{}",
            "tool_output": '{"currencies": ["USD"]}',
            "error": None,
        },
        {"step_index": 0, "step_type": "synthesis", "tool_name": None},
    ]
    save_trace(db, "msg_1", steps)

    traces = get_traces(db, "msg_1")
    assert len(traces) == 3
    assert traces[0]["step_type"] == "plan"
    assert traces[1]["step_type"] == "tool_call"
    assert traces[1]["tool_name"] == "ledger_info"
    assert traces[2]["step_type"] == "synthesis"


def test_get_traces_empty(db):
    traces = get_traces(db, "nonexistent")
    assert traces == []
