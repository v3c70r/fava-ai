import sqlite3
from pathlib import Path

from fava_ai.storage.schema import SCHEMA_VERSION, MIGRATIONS


class Database:
    def __init__(self, db_path: Path):
        self.db_path = Path(db_path)
        self._conn = None

    @property
    def conn(self) -> sqlite3.Connection:
        if self._conn is None:
            self._conn = sqlite3.connect(str(self.db_path))
            self._conn.row_factory = sqlite3.Row
            self._conn.execute("PRAGMA journal_mode=WAL")
            self._conn.execute("PRAGMA foreign_keys=ON")
        return self._conn

    def initialize(self):
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
                conn.executescript(MIGRATIONS[version])
                conn.execute(
                    "INSERT OR REPLACE INTO schema_version (version) VALUES (?)",
                    (version,),
                )

        conn.commit()

    def close(self):
        if self._conn:
            self._conn.close()
            self._conn = None
