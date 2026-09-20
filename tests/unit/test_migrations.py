"""Schema migration tests (v1 -> v2: message ordering via `seq`)."""

import sqlite3

from fava_ai.models.base import Message
from fava_ai.storage.conversations import load_messages, save_message
from fava_ai.storage.database import Database
from fava_ai.storage.schema import DDL, SCHEMA_VERSION


def _make_v1_db(path):
    """Create a database at schema version 1 with three same-timestamp messages."""
    conn = sqlite3.connect(path)
    conn.executescript(DDL)
    conn.execute("INSERT INTO schema_version (version) VALUES (1)")
    conn.execute(
        "INSERT INTO conversations (id, title, provider, model, created_at, updated_at) "
        "VALUES ('c1', 'Old', 'p', 'm', '2025-01-01T00:00:00Z', '2025-01-01T00:00:00Z')"
    )
    for i, content in enumerate(["first", "second", "third"]):
        conn.execute(
            "INSERT INTO messages (id, conversation_id, role, content, created_at) "
            "VALUES (?, 'c1', 'user', ?, '2025-01-01T00:00:00Z')",
            (f"m{i}", content),
        )
    conn.commit()
    conn.close()


def test_migration_adds_seq_and_backfills(tmp_path):
    path = tmp_path / "old.db"
    _make_v1_db(path)

    db = Database(path)
    db.initialize()

    columns = [row[1] for row in db.conn.execute("PRAGMA table_info(messages)")]
    assert "seq" in columns

    seqs = [row["seq"] for row in db.conn.execute("SELECT seq FROM messages ORDER BY seq")]
    assert seqs == [1, 2, 3]

    # Ordering is preserved after migration.
    messages = load_messages(db, "c1")
    assert [m.content for m in messages] == ["first", "second", "third"]

    version = db.conn.execute(
        "SELECT MAX(version) AS v FROM schema_version"
    ).fetchone()["v"]
    assert version == SCHEMA_VERSION
    db.close()


def test_new_messages_get_monotonic_seq(tmp_path):
    db = Database(tmp_path / "new.db")
    db.initialize()
    db.execute(
        "INSERT INTO conversations (id, title, provider, model) VALUES ('c', 't', 'p', 'm')"
    )
    db.commit()

    for content in ["a", "b", "c"]:
        save_message(db, "c", Message(role="user", content=content))

    rows = db.conn.execute(
        "SELECT content, seq FROM messages ORDER BY seq"
    ).fetchall()
    assert [r["content"] for r in rows] == ["a", "b", "c"]
    assert [r["seq"] for r in rows] == [1, 2, 3]
    db.close()


def test_initialize_is_idempotent(tmp_path):
    path = tmp_path / "db.sqlite"
    db = Database(path)
    db.initialize()
    db.initialize()  # must not re-run migrations / raise

    count = db.conn.execute(
        "SELECT COUNT(*) AS n FROM schema_version"
    ).fetchone()["n"]
    assert count == SCHEMA_VERSION
    db.close()
