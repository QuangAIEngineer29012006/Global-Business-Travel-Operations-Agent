"""Local training-only persistence for run summaries, scoped session context, and opt-in preferences."""

import json
import re
import sqlite3
import threading
from datetime import datetime, timezone
from pathlib import Path


PREFERENCE_VALUES = {
    "response_language": {"vi", "en", "vi-VN", "en-US"},
    "preferred_output_format": {"plain_text", "markdown", "checklist", "concise", "detailed"},
}
SENSITIVE_VALUE = re.compile(
    r"(passport|visa(?:\s|_)?(?:number|no|id)?|payment|credit\s*card|bank\s*account|"
    r"password|secret|api[_ -]?key|token|home\s+address)", re.IGNORECASE
)


class StateStore:
    """SQLite-backed agent state. Business facts are intentionally not persisted here."""

    def __init__(self, path):
        self.path = str(path)
        if self.path != ":memory:":
            Path(self.path).parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._db = sqlite3.connect(self.path, check_same_thread=False, timeout=10)
        self._db.row_factory = sqlite3.Row
        with self._lock:
            self._db.executescript(
                """
                PRAGMA foreign_keys = ON;
                CREATE TABLE IF NOT EXISTS runs (
                    run_id TEXT PRIMARY KEY,
                    request_id TEXT NOT NULL,
                    actor_id TEXT NOT NULL,
                    session_id TEXT NOT NULL,
                    workflow TEXT NOT NULL,
                    phase TEXT NOT NULL,
                    steps INTEGER NOT NULL,
                    max_steps INTEGER NOT NULL,
                    terminal_status TEXT NOT NULL,
                    reason_code TEXT NOT NULL,
                    artifact_ids TEXT NOT NULL,
                    evidence_ids TEXT NOT NULL,
                    trace TEXT NOT NULL,
                    completed_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS sessions (
                    actor_id TEXT NOT NULL,
                    session_id TEXT NOT NULL,
                    active_trip_id TEXT,
                    updated_at TEXT NOT NULL,
                    PRIMARY KEY (actor_id, session_id)
                );
                CREATE TABLE IF NOT EXISTS preferences (
                    actor_id TEXT NOT NULL,
                    key TEXT NOT NULL,
                    value TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    PRIMARY KEY (actor_id, key)
                );
                CREATE TABLE IF NOT EXISTS drafts (
                    sequence INTEGER PRIMARY KEY AUTOINCREMENT,
                    draft_id TEXT UNIQUE NOT NULL,
                    actor_id TEXT NOT NULL,
                    artifact_type TEXT NOT NULL,
                    status TEXT NOT NULL,
                    delivery_status TEXT NOT NULL,
                    source_ids TEXT NOT NULL,
                    content TEXT NOT NULL,
                    idempotency_key TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    UNIQUE(actor_id, idempotency_key)
                );
                CREATE TABLE IF NOT EXISTS approval_simulations (
                    sequence INTEGER PRIMARY KEY AUTOINCREMENT,
                    approval_id TEXT UNIQUE NOT NULL,
                    actor_id TEXT NOT NULL,
                    trip_id TEXT NOT NULL,
                    request_type TEXT NOT NULL,
                    status TEXT NOT NULL CHECK(status = 'pending'),
                    action_summary TEXT NOT NULL,
                    idempotency_key TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    UNIQUE(actor_id, idempotency_key)
                );
                """
            )
            self._db.commit()

    def close(self):
        with self._lock:
            self._db.close()

    def load_session(self, actor_id, session_id):
        if not actor_id or not session_id:
            return {}
        with self._lock:
            row = self._db.execute(
                "SELECT active_trip_id FROM sessions WHERE actor_id=? AND session_id=?",
                (actor_id, session_id),
            ).fetchone()
        return {"active_trip_id": row["active_trip_id"]} if row and row["active_trip_id"] else {}

    def save_session(self, actor_id, session_id, state):
        if not actor_id or not session_id:
            return
        trip_id = state.get("active_trip_id") if isinstance(state, dict) else None
        if trip_id is not None and not re.fullmatch(r"TRIP-\d{4}-\d{3}", str(trip_id)):
            trip_id = None
        now = datetime.now(timezone.utc).isoformat()
        with self._lock:
            self._db.execute(
                "INSERT INTO sessions(actor_id, session_id, active_trip_id, updated_at) VALUES(?,?,?,?) "
                "ON CONFLICT(actor_id, session_id) DO UPDATE SET active_trip_id=excluded.active_trip_id, "
                "updated_at=excluded.updated_at",
                (actor_id, session_id, trip_id, now),
            )
            self._db.commit()

    def save_run(self, request, result):
        actor_id = request.get("actor", {}).get("actor_id", "")
        trace = result.get("trace", [])
        final_budget = next((entry.get("budget", {}) for entry in reversed(trace)
                             if entry.get("action") == "terminal"), {})
        completed_at = datetime.now(timezone.utc).isoformat()
        values = (
            result.get("run_id", ""), request.get("request_id", ""), actor_id,
            request.get("session_id", ""), result.get("workflow", ""), "terminal",
            int(result.get("steps", 0)), int(final_budget.get("steps", "0/0").split("/")[-1] or 0),
            result.get("status", ""), result.get("reason_code", ""),
            json.dumps([a.get("draft_id") for a in result.get("artifacts", []) if a.get("draft_id")]),
            json.dumps([e.get("chunk_id") for e in result.get("evidence", []) if e.get("chunk_id")]),
            json.dumps(trace, ensure_ascii=False), completed_at,
        )
        with self._lock:
            self._db.execute(
                "INSERT OR REPLACE INTO runs(run_id, request_id, actor_id, session_id, workflow, phase, steps, "
                "max_steps, terminal_status, reason_code, artifact_ids, evidence_ids, trace, completed_at) "
                "VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)", values,
            )
            self._db.commit()

    def get_preference(self, actor_id):
        with self._lock:
            rows = self._db.execute(
                "SELECT key, value FROM preferences WHERE actor_id=? ORDER BY key", (actor_id,)
            ).fetchall()
        return {row["key"]: row["value"] for row in rows}

    def set_preference(self, actor_id, key, value):
        if key not in PREFERENCE_VALUES:
            raise ValueError("Preference key is not supported.")
        if value not in PREFERENCE_VALUES[key] or SENSITIVE_VALUE.search(value):
            raise ValueError("Preference value is not allowed.")
        now = datetime.now(timezone.utc).isoformat()
        with self._lock:
            self._db.execute(
                "INSERT INTO preferences(actor_id, key, value, updated_at) VALUES(?,?,?,?) "
                "ON CONFLICT(actor_id, key) DO UPDATE SET value=excluded.value, updated_at=excluded.updated_at",
                (actor_id, key, value, now),
            )
            self._db.commit()

    def delete_preference(self, actor_id, key=None):
        with self._lock:
            if key is None:
                cursor = self._db.execute("DELETE FROM preferences WHERE actor_id=?", (actor_id,))
            else:
                cursor = self._db.execute(
                    "DELETE FROM preferences WHERE actor_id=? AND key=?", (actor_id, key)
                )
            self._db.commit()
            return cursor.rowcount

    def create_draft(self, artifact_type, args, actor_id):
        key = args["idempotency_key"]
        if not actor_id:
            raise ValueError("A scoped actor ID is required for draft persistence.")
        source_ids = args["source_ids"]
        content = args["payload"]
        try:
            content_json = json.dumps(content, ensure_ascii=False, allow_nan=False)
        except (TypeError, ValueError):
            raise ValueError("Draft content is not valid JSON.") from None
        if not isinstance(content, dict) or len(content_json) > 64000:
            raise ValueError("Draft content is not valid or exceeds the sandbox limit.")
        if any(re.search(r"(passport|visa.?number|card|account|token|password|secret|address)", str(key), re.I)
               for key in self._walk_keys(content)):
            raise ValueError("Draft content contains a disallowed sensitive field.")
        if not all(isinstance(item, str) and re.fullmatch(r"[A-Za-z0-9_-]{1,80}", item) for item in source_ids):
            raise ValueError("Draft source IDs are not valid.")
        with self._lock:
            self._db.execute("BEGIN IMMEDIATE")
            try:
                row = self._db.execute("SELECT * FROM drafts WHERE actor_id=? AND idempotency_key=?",
                                       (actor_id, key)).fetchone()
                if row:
                    record = self._draft_record(row)
                    if record["artifact_type"] != artifact_type:
                        raise ValueError("Idempotency key is already assigned to another draft type.")
                    self._db.rollback()
                    return record, True
                created_at = datetime.now(timezone.utc).isoformat()
                self._db.execute(
                    "INSERT INTO drafts(draft_id, actor_id, artifact_type, status, delivery_status, source_ids, content, "
                    "idempotency_key, created_at) VALUES('',?,?,?,?,?,?,?,?)",
                    (actor_id, artifact_type, "draft_created", "not_sent", json.dumps(source_ids),
                     content_json, key, created_at),
                )
                sequence = self._db.execute("SELECT last_insert_rowid()").fetchone()[0]
                draft_id = f"DRAFT-{datetime.now(timezone.utc).year}-{sequence:03d}"
                self._db.execute("UPDATE drafts SET draft_id=? WHERE sequence=?", (draft_id, sequence))
                row = self._db.execute("SELECT * FROM drafts WHERE sequence=?", (sequence,)).fetchone()
                self._db.commit()
                return self._draft_record(row), False
            except Exception:
                self._db.rollback()
                raise

    @staticmethod
    def _walk_keys(value):
        if isinstance(value, dict):
            for key, item in value.items():
                yield key
                yield from StateStore._walk_keys(item)
        elif isinstance(value, list):
            for item in value:
                yield from StateStore._walk_keys(item)

    @staticmethod
    def _draft_record(row):
        return {"draft_id": row["draft_id"], "artifact_type": row["artifact_type"],
                "status": row["status"], "delivery_status": row["delivery_status"],
                "source_ids": json.loads(row["source_ids"]), "content": json.loads(row["content"]),
                "idempotency_key": row["idempotency_key"], "created_at": row["created_at"]}

    def create_approval_request(self, trip_id, action_summary, idempotency_key, actor_id):
        if not actor_id:
            raise ValueError("A scoped actor ID is required for approval persistence.")
        with self._lock:
            self._db.execute("BEGIN IMMEDIATE")
            try:
                row = self._db.execute(
                    "SELECT * FROM approval_simulations WHERE actor_id=? AND idempotency_key=?",
                    (actor_id, idempotency_key)
                ).fetchone()
                if row:
                    if row["trip_id"] != trip_id or row["action_summary"] != action_summary:
                        raise ValueError("Idempotency key is already assigned to another approval request.")
                    self._db.rollback()
                    return self._approval_record(row), True
                created_at = datetime.now(timezone.utc).isoformat()
                self._db.execute(
                    "INSERT INTO approval_simulations(approval_id, actor_id, trip_id, request_type, status, action_summary, "
                    "idempotency_key, created_at) VALUES('',?,?,?, 'pending',?,?,?)",
                    (actor_id, trip_id, "trip", action_summary, idempotency_key, created_at),
                )
                sequence = self._db.execute("SELECT last_insert_rowid()").fetchone()[0]
                approval_id = f"APR-{datetime.now(timezone.utc).year}-{900 + sequence:03d}"
                self._db.execute("UPDATE approval_simulations SET approval_id=? WHERE sequence=?",
                                 (approval_id, sequence))
                row = self._db.execute("SELECT * FROM approval_simulations WHERE sequence=?", (sequence,)).fetchone()
                self._db.commit()
                return self._approval_record(row), False
            except Exception:
                self._db.rollback()
                raise

    @staticmethod
    def _approval_record(row):
        return {key: row[key] for key in
                ("approval_id", "trip_id", "request_type", "status", "action_summary", "created_at")}

    def latest_approval_request(self, trip_id):
        with self._lock:
            row = self._db.execute(
                "SELECT * FROM approval_simulations WHERE trip_id=? ORDER BY sequence DESC LIMIT 1", (trip_id,)
            ).fetchone()
        return self._approval_record(row) if row else None
