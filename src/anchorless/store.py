"""SQLite: which stories we have seen, and which ones we already alerted on.

It lets "first seen" times and the breaking-news history survive restarts.
"""

from __future__ import annotations

import json
import sqlite3
from collections.abc import Iterable
from datetime import UTC, datetime, timedelta
from pathlib import Path

from .models import Story

_SCHEMA = """
CREATE TABLE IF NOT EXISTS seen (
    key TEXT PRIMARY KEY,
    first_seen REAL NOT NULL,
    outlet TEXT NOT NULL,
    title TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS alerts (
    cluster_key TEXT PRIMARY KEY,
    title TEXT NOT NULL,
    tokens TEXT NOT NULL,
    alerted_at REAL NOT NULL
);
"""


def _ts(d: datetime) -> float:
    return d.timestamp()


def _dt(ts: float) -> datetime:
    return datetime.fromtimestamp(ts, UTC)


class Store:
    def __init__(self, path: str | Path) -> None:
        path = Path(path)
        if str(path) != ":memory:":
            path.parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(str(path))
        self.db.executescript(_SCHEMA)

    def close(self) -> None:
        self.db.close()

    def is_empty(self) -> bool:
        return self.db.execute("SELECT 1 FROM seen LIMIT 1").fetchone() is None

    def mark_seen(self, stories: Iterable[Story], now: datetime) -> None:
        """Record new stories and fill in every story's ``first_seen``."""
        stories = list(stories)
        with self.db:
            self.db.executemany(
                "INSERT OR IGNORE INTO seen (key, first_seen, outlet, title) VALUES (?, ?, ?, ?)",
                [(s.key, _ts(now), s.outlet, s.title) for s in stories],
            )
        first: dict[str, float] = {}
        keys = [s.key for s in stories]
        for i in range(0, len(keys), 500):
            chunk = keys[i:i + 500]
            q = f"SELECT key, first_seen FROM seen WHERE key IN ({','.join('?' * len(chunk))})"
            first.update(self.db.execute(q, chunk).fetchall())
        for s in stories:
            if s.key in first:
                s.first_seen = _dt(first[s.key])

    def prune(self, now: datetime, keep: timedelta = timedelta(days=3)) -> None:
        cutoff = _ts(now - keep)
        with self.db:
            self.db.execute("DELETE FROM seen WHERE first_seen < ?", (cutoff,))
            self.db.execute("DELETE FROM alerts WHERE alerted_at < ?", (cutoff,))

    # --- breaking news ---

    def record_alert(self, cluster_key: str, title: str, tokens: set[str], now: datetime) -> None:
        with self.db:
            self.db.execute(
                "INSERT OR REPLACE INTO alerts (cluster_key, title, tokens, alerted_at) VALUES (?, ?, ?, ?)",
                (cluster_key, title, json.dumps(sorted(tokens)), _ts(now)),
            )

    def last_alert_at(self) -> datetime | None:
        row = self.db.execute("SELECT MAX(alerted_at) FROM alerts").fetchone()
        return _dt(row[0]) if row and row[0] is not None else None

    def recent_alerts(self, limit: int = 10) -> list[tuple[str, datetime]]:
        """The latest alerts, newest first: (headline, when)."""
        rows = self.db.execute("SELECT title, alerted_at FROM alerts ORDER BY alerted_at DESC LIMIT ?",
                               (limit,)).fetchall()
        return [(t, _dt(a)) for t, a in rows]

    def alerts(self) -> list[tuple[str, set[str], datetime]]:
        rows = self.db.execute("SELECT cluster_key, tokens, alerted_at FROM alerts").fetchall()
        return [(k, set(json.loads(t)), _dt(a)) for k, t, a in rows]
