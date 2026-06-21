import json
import uuid
from datetime import datetime


def save_trace(db, message_id: str, trace_steps: list[dict]):
    for step in trace_steps:
        trace_id = str(uuid.uuid4())
        db.conn.execute(
            """INSERT INTO traces (id, message_id, step_index, step_type, tool_name,
               tool_input, tool_output, bql_query, wiki_sources, started_at, completed_at, error)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                trace_id,
                message_id,
                step.get("step_index", 0),
                step.get("step_type", "plan"),
                step.get("tool_name"),
                json.dumps(step.get("tool_input")) if step.get("tool_input") else None,
                json.dumps(step.get("tool_output"))[:2000] if step.get("tool_output") else None,
                step.get("bql_query"),
                json.dumps(step.get("wiki_sources")) if step.get("wiki_sources") else None,
                step.get("started_at"),
                step.get("completed_at"),
                step.get("error"),
            ),
        )
    db.conn.commit()


def get_traces(db, message_id: str) -> list[dict]:
    rows = db.conn.execute(
        "SELECT * FROM traces WHERE message_id = ? ORDER BY step_index",
        (message_id,),
    ).fetchall()
    return [dict(r) for r in rows]
