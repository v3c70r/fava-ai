import json
import uuid


def save_trace(db, message_id: str, trace_steps: list[dict]):
    for step in trace_steps:
        tool_input = step.get("tool_input")
        if tool_input is not None:
            tool_input = tool_input if isinstance(tool_input, str) else json.dumps(tool_input)

        tool_output = step.get("tool_output")
        if tool_output is not None:
            tool_output = tool_output[:2000]

        wiki_sources = step.get("wiki_sources")
        if wiki_sources is not None:
            wiki_sources = json.dumps(wiki_sources)

        db.execute(
            """INSERT INTO traces (id, message_id, step_index, step_type, tool_name,
               tool_input, tool_output, bql_query, wiki_sources, started_at, completed_at, error)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                str(uuid.uuid4()),
                message_id,
                step.get("step_index", 0),
                step.get("step_type", "plan"),
                step.get("tool_name"),
                tool_input,
                tool_output,
                step.get("bql_query"),
                wiki_sources,
                step.get("started_at"),
                step.get("completed_at"),
                step.get("error"),
            ),
        )
    db.commit()


def get_traces(db, message_id: str) -> list[dict]:
    rows = db.execute(
        "SELECT * FROM traces WHERE message_id = ? ORDER BY step_index",
        (message_id,),
    ).fetchall()
    return [dict(r) for r in rows]
