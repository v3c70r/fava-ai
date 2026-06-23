import sqlite3
import threading
from pathlib import Path

from fava_ai.storage.schema import SCHEMA_VERSION, MIGRATIONS


class Database:
    def __init__(self, db_path: Path):
        self.db_path = Path(db_path)
        self._conn = None
        self._lock = threading.Lock()

    @property
    def conn(self) -> sqlite3.Connection:
        if self._conn is None:
            self._conn = sqlite3.connect(
                str(self.db_path),
                check_same_thread=False,
            )
            self._conn.row_factory = sqlite3.Row
            self._conn.execute("PRAGMA journal_mode=WAL")
            self._conn.execute("PRAGMA foreign_keys=ON")
        return self._conn

    @property
    def lock(self) -> threading.Lock:
        return self._lock

    def execute(self, sql: str, params=()):
        with self._lock:
            return self.conn.execute(sql, params)

    def executescript(self, sql: str):
        with self._lock:
            self.conn.executescript(sql)

    def commit(self):
        with self._lock:
            self.conn.commit()

    def initialize(self):
        with self._lock:
            conn = self.conn

            current_version = 0
            try:
                row = conn.execute(
                    "SELECT version FROM schema_version ORDER BY version DESC LIMIT 1"
                ).fetchone()
                if row:
                    current_version = row["version"]
            except sqlite3.OperationalError:
                pass

            for version in sorted(MIGRATIONS.keys()):
                if version > current_version:
                    try:
                        conn.executescript(MIGRATIONS[version])
                        conn.execute(
                            "INSERT OR REPLACE INTO schema_version (version) VALUES (?)",
                            (version,),
                        )
                        conn.commit()
                    except Exception:
                        conn.rollback()
                        raise

    def close(self):
        with self._lock:
            if self._conn:
                self._conn.close()
                self._conn = None
