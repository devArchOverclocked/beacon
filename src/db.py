from __future__ import annotations

import sqlite3
from datetime import datetime
from pathlib import Path


class Database:
    """SQLite-backed store for indexed SharePoint files."""

    def __init__(self, path: Path) -> None:
        self._path = path
        # Ensure the parent directory exists before opening the connection.
        path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(str(path), check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self.init_schema()

    # ------------------------------------------------------------------
    # Schema
    # ------------------------------------------------------------------

    def init_schema(self) -> None:
        """Create tables if they do not already exist."""
        with self._conn:
            self._conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS files (
                    id        INTEGER PRIMARY KEY AUTOINCREMENT,
                    name      TEXT NOT NULL,
                    path      TEXT NOT NULL,
                    url       TEXT NOT NULL UNIQUE,
                    file_type TEXT NOT NULL
                );

                CREATE INDEX IF NOT EXISTS idx_files_name ON files(name);
                CREATE INDEX IF NOT EXISTS idx_files_path ON files(path);

                CREATE TABLE IF NOT EXISTS meta (
                    key   TEXT PRIMARY KEY,
                    value TEXT NOT NULL
                );
                """
            )

    # ------------------------------------------------------------------
    # Write operations
    # ------------------------------------------------------------------

    def upsert_files(self, files: list[dict]) -> None:
        """Insert or replace file records.

        Each dict must contain the keys: name, path, url, file_type.
        ``url`` is used as the uniqueness key (UNIQUE constraint).
        """
        with self._conn:
            self._conn.executemany(
                """
                INSERT INTO files (name, path, url, file_type)
                VALUES (:name, :path, :url, :file_type)
                ON CONFLICT(url) DO UPDATE SET
                    name      = excluded.name,
                    path      = excluded.path,
                    file_type = excluded.file_type
                """,
                files,
            )

    def clear_files(self) -> None:
        """Delete all file records and record the current timestamp."""
        with self._conn:
            self._conn.execute("DELETE FROM files")
            self._conn.execute(
                "INSERT OR REPLACE INTO meta (key, value) VALUES ('last_indexed', ?)",
                (datetime.utcnow().isoformat(),),
            )

    # ------------------------------------------------------------------
    # Read operations
    # ------------------------------------------------------------------

    def get_all_files(self) -> list[dict]:
        """Return every file record as a plain dict."""
        cursor = self._conn.execute(
            "SELECT name, path, url, file_type FROM files ORDER BY name"
        )
        return [dict(row) for row in cursor.fetchall()]

    def get_last_indexed(self) -> datetime | None:
        """Return the UTC datetime of the last successful index run, or None."""
        cursor = self._conn.execute(
            "SELECT value FROM meta WHERE key = 'last_indexed'"
        )
        row = cursor.fetchone()
        if row is None:
            return None
        try:
            return datetime.fromisoformat(row["value"])
        except ValueError:
            return None

    def get_file_count(self) -> int:
        """Return the total number of indexed files."""
        cursor = self._conn.execute("SELECT COUNT(*) FROM files")
        return cursor.fetchone()[0]

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def close(self) -> None:
        """Close the underlying SQLite connection."""
        self._conn.close()
