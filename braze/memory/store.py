"""Durable run state in SQLite.

Every write here commits before the thing it describes is allowed to happen,
which is the only reason a resume can tell "I was about to do that" apart from
"I did that". WAL mode is what lets a reader list runs while one is writing.
"""

from __future__ import annotations

import json
import sqlite3
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

DB_PATH = Path.home() / ".braze" / "runs.db"

SCHEMA = """
CREATE TABLE IF NOT EXISTS runs (
    id             TEXT PRIMARY KEY,
    task           TEXT NOT NULL,
    workspace      TEXT NOT NULL,
    model          TEXT NOT NULL,
    created        TEXT NOT NULL,
    updated        TEXT NOT NULL,
    status         TEXT NOT NULL,
    stopped_reason TEXT,
    answer         TEXT,
    turns          INTEGER NOT NULL DEFAULT 0,
    tokens         INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS messages (
    run_id     TEXT NOT NULL,
    seq        INTEGER NOT NULL,
    turn       INTEGER NOT NULL,
    role       TEXT NOT NULL,
    body       TEXT NOT NULL,
    tokens     INTEGER NOT NULL DEFAULT 0,
    dropped_at INTEGER,
    PRIMARY KEY (run_id, seq)
);

CREATE TABLE IF NOT EXISTS steps (
    run_id      TEXT NOT NULL,
    call_id     TEXT NOT NULL,
    turn        INTEGER NOT NULL,
    tool        TEXT NOT NULL,
    arguments   TEXT NOT NULL,
    status      TEXT NOT NULL,
    fingerprint TEXT,
    output      TEXT,
    PRIMARY KEY (run_id, call_id)
);

CREATE TABLE IF NOT EXISTS budget (
    run_id TEXT NOT NULL,
    turn   INTEGER NOT NULL,
    before INTEGER NOT NULL,
    after  INTEGER NOT NULL,
    PRIMARY KEY (run_id, turn)
);
"""

RUNNING = "running"
FINISHED = "finished"
STOPPED = "stopped"
INTERRUPTED = "interrupted"

STARTED = "started"
DONE = "done"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


@dataclass
class Step:
    call_id: str
    turn: int
    tool: str
    arguments: str
    status: str
    fingerprint: str | None
    output: str | None


@dataclass
class Run:
    id: str
    task: str
    workspace: str
    model: str
    created: str
    updated: str
    status: str
    stopped_reason: str | None
    answer: str | None
    turns: int
    tokens: int

    @property
    def resumable(self) -> bool:
        return self.status in {RUNNING, INTERRUPTED}


class Store:
    def __init__(self, path: Path | str = DB_PATH):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(self.path, isolation_level=None)
        self.db.row_factory = sqlite3.Row
        # WAL lets `braze --runs` read while a run is mid-write. NORMAL still
        # fsyncs the WAL on commit, which is the durability we actually need.
        self.db.execute("PRAGMA journal_mode=WAL")
        self.db.execute("PRAGMA synchronous=NORMAL")
        self.db.executescript(SCHEMA)

    def close(self) -> None:
        self.db.close()

    # -- runs ---------------------------------------------------------------

    def create_run(self, task: str, workspace: str, model: str) -> str:
        run_id = uuid.uuid4().hex[:12]
        now = _now()
        self.db.execute(
            "INSERT INTO runs (id, task, workspace, model, created, updated, status)"
            " VALUES (?, ?, ?, ?, ?, ?, ?)",
            (run_id, task, workspace, model, now, now, RUNNING),
        )
        return run_id

    def get_run(self, run_id: str) -> Run | None:
        row = self.db.execute("SELECT * FROM runs WHERE id = ?", (run_id,)).fetchone()
        return Run(**dict(row)) if row else None

    def find_run(self, prefix: str) -> Run | None:
        """Accept a unique id prefix, because nobody types twelve hex characters."""
        rows = self.db.execute(
            "SELECT * FROM runs WHERE id LIKE ? ORDER BY created DESC", (prefix + "%",)
        ).fetchall()
        return Run(**dict(rows[0])) if len(rows) == 1 else None

    def list_runs(self, limit: int = 20) -> list[Run]:
        rows = self.db.execute(
            "SELECT * FROM runs ORDER BY created DESC LIMIT ?", (limit,)
        ).fetchall()
        return [Run(**dict(row)) for row in rows]

    def update_run(self, run_id: str, **fields) -> None:
        fields["updated"] = _now()
        assignments = ", ".join(f"{k} = ?" for k in fields)
        self.db.execute(
            f"UPDATE runs SET {assignments} WHERE id = ?", (*fields.values(), run_id)
        )

    # -- messages -----------------------------------------------------------

    def append_message(self, run_id: str, turn: int, body: dict, tokens: int) -> int:
        seq = self.db.execute(
            "SELECT COALESCE(MAX(seq), -1) + 1 FROM messages WHERE run_id = ?", (run_id,)
        ).fetchone()[0]
        self.db.execute(
            "INSERT INTO messages (run_id, seq, turn, role, body, tokens)"
            " VALUES (?, ?, ?, ?, ?, ?)",
            (run_id, seq, turn, body.get("role", ""), json.dumps(body), tokens),
        )
        return seq

    def live_messages(self, run_id: str) -> list[dict]:
        """The context as it stands: everything compaction has not dropped."""
        rows = self.db.execute(
            "SELECT body FROM messages WHERE run_id = ? AND dropped_at IS NULL"
            " ORDER BY seq",
            (run_id,),
        ).fetchall()
        return [json.loads(row["body"]) for row in rows]

    def all_messages(self, run_id: str) -> list[dict]:
        """Everything ever said, including what compaction dropped."""
        rows = self.db.execute(
            "SELECT body FROM messages WHERE run_id = ? ORDER BY seq", (run_id,)
        ).fetchall()
        return [json.loads(row["body"]) for row in rows]

    def live_seqs(self, run_id: str) -> list[int]:
        rows = self.db.execute(
            "SELECT seq FROM messages WHERE run_id = ? AND dropped_at IS NULL"
            " ORDER BY seq",
            (run_id,),
        ).fetchall()
        return [row["seq"] for row in rows]

    def drop_messages(self, run_id: str, seqs: list[int], turn: int) -> None:
        self.db.executemany(
            "UPDATE messages SET dropped_at = ? WHERE run_id = ? AND seq = ?",
            [(turn, run_id, seq) for seq in seqs],
        )

    # -- steps --------------------------------------------------------------

    def begin_step(
        self, run_id: str, call_id: str, turn: int, tool: str,
        arguments: str, fingerprint: str | None,
    ) -> None:
        self.db.execute(
            "INSERT OR REPLACE INTO steps"
            " (run_id, call_id, turn, tool, arguments, status, fingerprint, output)"
            " VALUES (?, ?, ?, ?, ?, ?, ?, NULL)",
            (run_id, call_id, turn, tool, arguments, STARTED, fingerprint),
        )

    def finish_step(self, run_id: str, call_id: str, output: str) -> None:
        self.db.execute(
            "UPDATE steps SET status = ?, output = ? WHERE run_id = ? AND call_id = ?",
            (DONE, output, run_id, call_id),
        )

    def get_step(self, run_id: str, call_id: str) -> Step | None:
        row = self.db.execute(
            "SELECT call_id, turn, tool, arguments, status, fingerprint, output"
            " FROM steps WHERE run_id = ? AND call_id = ?",
            (run_id, call_id),
        ).fetchone()
        return Step(**dict(row)) if row else None

    # -- budget -------------------------------------------------------------

    def record_budget(self, run_id: str, turn: int, before: int, after: int) -> None:
        self.db.execute(
            "INSERT OR REPLACE INTO budget (run_id, turn, before, after)"
            " VALUES (?, ?, ?, ?)",
            (run_id, turn, before, after),
        )

    def budget_history(self, run_id: str) -> list[tuple[int, int, int]]:
        rows = self.db.execute(
            "SELECT turn, before, after FROM budget WHERE run_id = ? ORDER BY turn",
            (run_id,),
        ).fetchall()
        return [(r["turn"], r["before"], r["after"]) for r in rows]
