"""Unit tests for storage/ modules."""
import pytest
from pathlib import Path

from fava_ai.storage.database import Database
from fava_ai.storage.schema import SCHEMA_VERSION


def test_database_initialize(tmp_dir):
    db_path = tmp_dir / "test.db"
    db = Database(db_path)
    db.initialize()

    tables = db.conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
    ).fetchall()
    table_names = [t["name"] for t in tables]
    assert "conversations" in table_names
    assert "messages" in table_names
    assert "traces" in table_names
    assert "config" in table_names
    assert "prompt_registry" in table_names

    version = db.conn.execute("SELECT version FROM schema_version").fetchone()
    assert version["version"] == SCHEMA_VERSION

    db.close()


def test_database_foreign_keys_enabled(tmp_dir):
    db_path = tmp_dir / "test.db"
    db = Database(db_path)
    db.initialize()
    fk = db.conn.execute("PRAGMA foreign_keys").fetchone()[0]
    assert fk == 1
    db.close()


def test_database_wal_mode(tmp_dir):
    db_path = tmp_dir / "test.db"
    db = Database(db_path)
    db.initialize()
    journal = db.conn.execute("PRAGMA journal_mode").fetchone()[0]
    assert journal.lower() == "wal"
    db.close()
