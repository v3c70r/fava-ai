import json
import uuid
from datetime import datetime, timezone

from fava_ai.models.base import Message


def list_conversations(db) -> list[dict]:
    rows = db.conn.execute(
        "SELECT id, title, provider, model, created_at, updated_at "
        "FROM conversations ORDER BY updated_at DESC"
    ).fetchall()
    return [dict(r) for r in rows]


def create_conversation(db, title: str = "", provider: str = "", model: str = "", id: str = None) -> dict:
    conv_id = id or str(uuid.uuid4())
    now = datetime.now(timezone.utc).isoformat() + "Z"
    if not title:
        title = "New conversation"
    db.conn.execute(
        "INSERT INTO conversations (id, title, provider, model, created_at, updated_at) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        (conv_id, title, provider, model, now, now),
    )
    db.conn.commit()
    return {
        "id": conv_id,
        "title": title,
        "provider": provider,
        "model": model,
        "created_at": now,
        "updated_at": now,
    }


def get_conversation(db, conv_id: str) -> dict | None:
    row = db.conn.execute(
        "SELECT * FROM conversations WHERE id = ?", (conv_id,)
    ).fetchone()
    if not row:
        return None

    messages = db.conn.execute(
        "SELECT * FROM messages WHERE conversation_id = ? ORDER BY created_at",
        (conv_id,),
    ).fetchall()

    conv = dict(row)
    conv["messages"] = [dict(m) for m in messages]
    return conv


def delete_conversation(db, conv_id: str):
    db.conn.execute("DELETE FROM conversations WHERE id = ?", (conv_id,))
    db.conn.commit()


def save_message(db, conv_id: str, message: Message):
    msg_id = str(uuid.uuid4())
    now = datetime.now(timezone.utc).isoformat() + "Z"

    tool_calls_json = None
    if message.tool_calls:
        tool_calls_json = json.dumps(
            [tc.to_dict() for tc in message.tool_calls], ensure_ascii=False
        )

    db.conn.execute(
        "INSERT INTO messages (id, conversation_id, role, content, tool_calls, "
        "tool_call_id, name, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        (
            msg_id,
            conv_id,
            message.role,
            message.content,
            tool_calls_json,
            message.tool_call_id,
            message.name,
            now,
        ),
    )

    db.conn.execute(
        "UPDATE conversations SET updated_at = ? WHERE id = ?",
        (now, conv_id),
    )

    db.conn.commit()
    return msg_id


def load_messages(db, conv_id: str) -> list[Message]:
    rows = db.conn.execute(
        "SELECT * FROM messages WHERE conversation_id = ? ORDER BY created_at",
        (conv_id,),
    ).fetchall()

    messages = []
    for row in rows:
        r = dict(row)
        tool_calls = None
        if r.get("tool_calls"):
            try:
                raw = json.loads(r["tool_calls"])
                from fava_ai.models.base import ToolCall, FunctionCall
                tool_calls = [
                    ToolCall(
                        id=tc["id"],
                        function=FunctionCall(
                            name=tc["function"]["name"],
                            arguments=tc["function"]["arguments"],
                        ),
                    )
                    for tc in raw
                ]
            except (json.JSONDecodeError, KeyError):
                pass

        messages.append(Message(
            role=r["role"],
            content=r.get("content"),
            tool_calls=tool_calls,
            tool_call_id=r.get("tool_call_id"),
            name=r.get("name"),
        ))

    return messages


def update_title(db, conv_id: str, title: str):
    now = datetime.now(timezone.utc).isoformat() + "Z"
    db.conn.execute(
        "UPDATE conversations SET title = ?, updated_at = ? WHERE id = ?",
        (title, now, conv_id),
    )
    db.conn.commit()
