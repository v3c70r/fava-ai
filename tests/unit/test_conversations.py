"""Unit tests for conversations storage."""
import pytest

from fava_ai.storage.database import Database
from fava_ai.storage.conversations import (
    create_conversation,
    list_conversations,
    get_conversation,
    delete_conversation,
    save_message,
    load_messages,
    update_title,
)
from fava_ai.models.base import Message


@pytest.fixture
def db(tmp_path):
    db_path = tmp_path / "test.db"
    d = Database(db_path)
    d.initialize()
    yield d
    d.close()


def test_create_and_list_conversation(db):
    conv = create_conversation(db, "Test conv", "ollama", "llama3")
    assert conv["title"] == "Test conv"
    assert conv["provider"] == "ollama"
    assert conv["model"] == "llama3"

    convs = list_conversations(db)
    assert len(convs) == 1
    assert convs[0]["id"] == conv["id"]


def test_create_conversation_default_title(db):
    conv = create_conversation(db, "", "openai", "gpt-4")
    assert conv["title"] == "New conversation"


def test_get_conversation(db):
    conv = create_conversation(db, "Test", "ollama", "llama3")
    loaded = get_conversation(db, conv["id"])
    assert loaded is not None
    assert loaded["title"] == "Test"
    assert loaded["messages"] == []


def test_get_nonexistent_conversation(db):
    assert get_conversation(db, "nonexistent") is None


def test_delete_conversation(db):
    conv = create_conversation(db, "To delete", "ollama", "llama3")
    delete_conversation(db, conv["id"])
    assert get_conversation(db, conv["id"]) is None
    assert len(list_conversations(db)) == 0


def test_delete_cascades_messages(db):
    conv = create_conversation(db, "Test", "ollama", "llama3")
    msg = Message(role="user", content="Hello")
    save_message(db, conv["id"], msg)

    delete_conversation(db, conv["id"])

    msgs = db.conn.execute(
        "SELECT * FROM messages WHERE conversation_id = ?", (conv["id"],)
    ).fetchall()
    assert len(msgs) == 0


def test_save_and_load_messages(db):
    conv = create_conversation(db, "Test", "ollama", "llama3")

    msg1 = Message(role="user", content="Hello")
    save_message(db, conv["id"], msg1)

    msg2 = Message(role="assistant", content="Hi there")
    save_message(db, conv["id"], msg2)

    messages = load_messages(db, conv["id"])
    assert len(messages) == 2
    assert messages[0].role == "user"
    assert messages[0].content == "Hello"
    assert messages[1].role == "assistant"
    assert messages[1].content == "Hi there"


def test_save_message_with_tool_calls(db):
    from fava_ai.models.base import ToolCall, FunctionCall

    conv = create_conversation(db, "Test", "ollama", "llama3")
    msg = Message(
        role="assistant",
        content=None,
        tool_calls=[
            ToolCall(
                id="call_1",
                function=FunctionCall(name="ledger_info", arguments="{}"),
            )
        ],
    )
    save_message(db, conv["id"], msg)

    messages = load_messages(db, conv["id"])
    assert len(messages) == 1
    assert messages[0].tool_calls is not None
    assert len(messages[0].tool_calls) == 1
    assert messages[0].tool_calls[0].function.name == "ledger_info"


def test_save_tool_message(db):
    conv = create_conversation(db, "Test", "ollama", "llama3")
    msg = Message(
        role="tool",
        content='{"result": "ok"}',
        tool_call_id="call_1",
        name="ledger_info",
    )
    save_message(db, conv["id"], msg)

    messages = load_messages(db, conv["id"])
    assert len(messages) == 1
    assert messages[0].role == "tool"
    assert messages[0].tool_call_id == "call_1"


def test_update_title(db):
    conv = create_conversation(db, "Old title", "ollama", "llama3")
    update_title(db, conv["id"], "New title")
    loaded = get_conversation(db, conv["id"])
    assert loaded["title"] == "New title"
