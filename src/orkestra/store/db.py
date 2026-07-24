"""SQLite connection management and migrations.

WAL mode, foreign keys on, one connection per kernel process. All state
mutation flows through explicit transactions (``with db.tx():``) so a
crash can never leave half-applied transitions (threat T13).
"""

from __future__ import annotations

import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

from orkestra.errors import StoreError
from orkestra.store.migrations import MIGRATIONS


class Database:
    """Thin wrapper owning the SQLite connection and migration chain."""

    def __init__(self, path: Path | str) -> None:
        self.path = Path(path)
        if self.path != Path(":memory:"):
            self.path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(str(self.path), isolation_level=None)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute("PRAGMA foreign_keys=ON")
        self._conn.execute("PRAGMA busy_timeout=5000")
        self._in_tx = False
        self._migrate()

    def _migrate(self) -> None:
        self._conn.execute(
            "CREATE TABLE IF NOT EXISTS schema_version (version INTEGER NOT NULL)"
        )
        row = self._conn.execute("SELECT version FROM schema_version").fetchone()
        current = int(row["version"]) if row else 0
        if current > len(MIGRATIONS):
            msg = (
                f"database schema version {current} is newer than this Orkestra "
                f"supports ({len(MIGRATIONS)}); upgrade Orkestra"
            )
            raise StoreError(msg)
        if not row:
            self._conn.execute("INSERT INTO schema_version (version) VALUES (0)")
        for index in range(current, len(MIGRATIONS)):
            # executescript() auto-commits any pending transaction first, so
            # atomicity comes from BEGIN/COMMIT embedded in the script itself;
            # the version bump is part of the same transaction. index+1 is a
            # trusted integer, not external input.
            script = (
                "BEGIN IMMEDIATE;\n"
                f"{MIGRATIONS[index]}\n"
                f"UPDATE schema_version SET version = {index + 1};\n"
                "COMMIT;"
            )
            try:
                self._conn.executescript(script)
            except sqlite3.Error as exc:
                try:
                    self._conn.execute("ROLLBACK")
                except sqlite3.Error:
                    pass
                msg = f"migration {index + 1} failed: {exc}"
                raise StoreError(msg) from exc

    @contextmanager
    def tx(self) -> Iterator[sqlite3.Connection]:
        """Serialized write transaction (BEGIN IMMEDIATE)."""
        if self._in_tx:
            # Nested use shares the outer transaction.
            yield self._conn
            return
        self._in_tx = True
        try:
            self._conn.execute("BEGIN IMMEDIATE")
            yield self._conn
            self._conn.execute("COMMIT")
        except BaseException:
            self._conn.execute("ROLLBACK")
            raise
        finally:
            self._in_tx = False

    def query(self, sql: str, params: tuple[object, ...] = ()) -> list[sqlite3.Row]:
        return list(self._conn.execute(sql, params).fetchall())

    def query_one(self, sql: str, params: tuple[object, ...] = ()) -> sqlite3.Row | None:
        return self._conn.execute(sql, params).fetchone()

    def close(self) -> None:
        self._conn.close()
