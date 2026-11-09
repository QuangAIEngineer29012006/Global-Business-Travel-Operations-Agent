import hashlib
import json
import secrets
import sqlite3
import time
import uuid
from contextlib import contextmanager
from pathlib import Path

from .config import ROOT
from .models import Approval, ExpenseReport, Itinerary, PolicyChunk, Profile, Trip


class StoreError(Exception):
    def __init__(self, code, status=400):
        self.code = code
        self.status = status


def digest(payload):
    return hashlib.sha256(json.dumps(payload, ensure_ascii=False, sort_keys=True).encode()).hexdigest()


@contextmanager
def transaction(conn: sqlite3.Connection):
    if conn.in_transaction:
        yield conn
        return
    conn.execute("BEGIN IMMEDIATE")
    try:
        yield conn
    except BaseException:
        conn.execute("ROLLBACK")
        raise
    else:
        conn.execute("COMMIT")


SCHEMA = """
CREATE TABLE IF NOT EXISTS mock_records(kind TEXT, id TEXT, payload TEXT NOT NULL, PRIMARY KEY(kind,id));
CREATE TABLE IF NOT EXISTS settings(key TEXT PRIMARY KEY, value TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS sessions(session_id TEXT PRIMARY KEY, user_id TEXT NOT NULL, role TEXT NOT NULL,
 token_hash TEXT NOT NULL UNIQUE, expires_at INTEGER NOT NULL, context TEXT NOT NULL DEFAULT '{}');
CREATE TABLE IF NOT EXISTS preferences(user_id TEXT PRIMARY KEY, payload TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS runs(run_id TEXT PRIMARY KEY, session_id TEXT NOT NULL, user_id TEXT NOT NULL,
 request_id TEXT NOT NULL, request_hash TEXT NOT NULL, status TEXT NOT NULL, payload TEXT,
 UNIQUE(session_id,request_id));
CREATE TABLE IF NOT EXISTS drafts(draft_id TEXT PRIMARY KEY, user_id TEXT NOT NULL, session_id TEXT NOT NULL,
 request_hash TEXT NOT NULL, payload TEXT NOT NULL);
"""


class Store:
    def __init__(self, workspace, dataset=None, policies=None):
        self.workspace = Path(workspace)
        self.workspace.mkdir(parents=True, exist_ok=True)
        self.path = self.workspace / "training.db"
        self.dataset = dataset if dataset is not None else json.loads((ROOT / "data/training.json").read_text())
        self.policy_seed = policies if policies is not None else json.loads((ROOT / "data/policies.json").read_text())
        with self.connection() as conn:
            conn.executescript(SCHEMA)
            if not conn.execute("SELECT 1 FROM settings WHERE key='seeded'").fetchone():
                with transaction(conn):
                    models = {"trips": (Trip, "trip_id"), "profiles": (Profile, "traveler_id"),
                              "itineraries": (Itinerary, "trip_id"), "approvals": (Approval, "trip_id"),
                              "reports": (ExpenseReport, "report_id")}
                    for kind, (model, id_field) in models.items():
                        for raw in self.dataset[kind]:
                            row = model.model_validate(raw).model_dump()
                            conn.execute("INSERT INTO mock_records VALUES (?,?,?)", (kind, row[id_field], json.dumps(row)))
                    for raw in self.policy_seed:
                        row = PolicyChunk.model_validate(raw).model_dump()
                        conn.execute("INSERT INTO mock_records VALUES ('policies',?,?)", (row["chunk_id"], json.dumps(row)))
                    conn.execute("INSERT INTO settings VALUES ('seeded','1')")

    @contextmanager
    def connection(self):
        conn = sqlite3.connect(self.path, isolation_level=None, timeout=10)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        try:
            yield conn
        finally:
            conn.close()

    def read_record(self, kind, record_id):
        with self.connection() as conn:
            row = conn.execute("SELECT payload FROM mock_records WHERE kind=? AND id=?", (kind, record_id)).fetchone()
        return json.loads(row[0]) if row else None

    def records(self, kind):
        with self.connection() as conn:
            return [json.loads(r[0]) for r in conn.execute("SELECT payload FROM mock_records WHERE kind=? ORDER BY id", (kind,))]

    def replace_record(self, kind, record_id, payload):
        """Fixture maintenance, used by tests and explicit mock approval simulation; never registered as a tool."""
        with self.connection() as conn:
            conn.execute("INSERT INTO mock_records VALUES (?,?,?) ON CONFLICT(kind,id) DO UPDATE SET payload=excluded.payload",
                         (kind, record_id, json.dumps(payload)))

    def request_mock_approval(self, trip_id, summary):
        with self.connection() as conn, transaction(conn):
            row = conn.execute("SELECT payload FROM mock_records WHERE kind='approvals' AND id=?", (trip_id,)).fetchone()
            if row is None:
                raise StoreError("not_found", 404)
            approval = json.loads(row[0])
            if approval["status"] != "not_requested":
                raise StoreError("approval_already_decided_or_pending", 409)
            approval.update(status="pending", action_summary=summary)
            conn.execute("UPDATE mock_records SET payload=? WHERE kind='approvals' AND id=?", (json.dumps(approval), trip_id))
        return approval

    def resolve_mock_approval(self, session, trip_id, status):
        if session["role"] != "approver":
            raise StoreError("approver_required", 403)
        with self.connection() as conn, transaction(conn):
            row = conn.execute("SELECT payload FROM mock_records WHERE kind='approvals' AND id=?", (trip_id,)).fetchone()
            if row is None:
                raise StoreError("not_found", 404)
            approval = json.loads(row[0])
            if approval["status"] != "pending":
                raise StoreError("approval_not_pending", 409)
            approval["status"] = status
            conn.execute("UPDATE mock_records SET payload=? WHERE kind='approvals' AND id=?", (json.dumps(approval), trip_id))
        return approval

    def create_session(self, user_id):
        user = next((u for u in self.dataset["users"] if u["user_id"] == user_id), None)
        if user is None:
            raise StoreError("unknown_training_user", 404)
        token, sid = secrets.token_urlsafe(32), uuid.uuid4().hex
        expires = int(time.time()) + 86400
        with self.connection() as conn:
            conn.execute("INSERT INTO sessions(session_id,user_id,role,token_hash,expires_at) VALUES (?,?,?,?,?)",
                         (sid, user_id, user["role"], hashlib.sha256(token.encode()).hexdigest(), expires))
        return {"session_id": sid, "user_id": user_id, "role": user["role"], "token": token,
                "expires_at": expires, "training_only": True}

    def authenticate(self, authorization):
        scheme, _, token = (authorization or "").partition(" ")
        if scheme.lower() != "bearer" or not 20 <= len(token) <= 200:
            raise StoreError("invalid_session", 401)
        with self.connection() as conn:
            row = conn.execute("SELECT * FROM sessions WHERE token_hash=? AND expires_at>?",
                               (hashlib.sha256(token.encode()).hexdigest(), int(time.time()))).fetchone()
        if row is None:
            raise StoreError("invalid_session", 401)
        return {"session_id": row["session_id"], "user_id": row["user_id"], "role": row["role"],
                "context": json.loads(row["context"])}

    def revoke(self, sid):
        with self.connection() as conn:
            conn.execute("DELETE FROM sessions WHERE session_id=?", (sid,))

    def session_is_active(self, sid):
        with self.connection() as conn:
            return conn.execute("SELECT 1 FROM sessions WHERE session_id=? AND expires_at>?",
                                (sid, int(time.time()))).fetchone() is not None

    def update_context(self, sid, context):
        allowed = {k: v for k, v in context.items() if k in {"active_trip_id", "active_report_id"}}
        with self.connection() as conn:
            conn.execute("UPDATE sessions SET context=? WHERE session_id=?", (json.dumps(allowed), sid))

    def preferences(self, user_id):
        with self.connection() as conn:
            row = conn.execute("SELECT payload FROM preferences WHERE user_id=?", (user_id,)).fetchone()
        return json.loads(row[0]) if row else {}

    def save_preferences(self, user_id, values):
        current = self.preferences(user_id)
        current.update(values)
        with self.connection() as conn:
            conn.execute("INSERT INTO preferences VALUES (?,?) ON CONFLICT(user_id) DO UPDATE SET payload=excluded.payload",
                         (user_id, json.dumps(current)))
        return current

    def delete_preferences(self, user_id):
        with self.connection() as conn:
            conn.execute("DELETE FROM preferences WHERE user_id=?", (user_id,))

    def begin_run(self, session, request_id, request_hash):
        with self.connection() as conn, transaction(conn):
            row = conn.execute("SELECT * FROM runs WHERE session_id=? AND request_id=?",
                               (session["session_id"], request_id)).fetchone()
            if row:
                if row["request_hash"] != request_hash:
                    raise StoreError("idempotency_conflict", 409)
                if row["status"] == "running":
                    raise StoreError("run_in_progress", 409)
                return row["run_id"], json.loads(row["payload"])
            rid = uuid.uuid4().hex
            conn.execute("INSERT INTO runs VALUES (?,?,?,?,?,'running',NULL)",
                         (rid, session["session_id"], session["user_id"], request_id, request_hash))
            return rid, None

    def finish_run(self, run_id, payload):
        with self.connection() as conn:
            conn.execute("UPDATE runs SET status='done',payload=? WHERE run_id=?", (json.dumps(payload, ensure_ascii=False), run_id))

    def get_run(self, session, run_id):
        with self.connection() as conn:
            row = conn.execute("SELECT payload,status FROM runs WHERE run_id=? AND session_id=? AND user_id=?",
                               (run_id, session["session_id"], session["user_id"])).fetchone()
        if row is None:
            raise StoreError("run_not_found", 404)
        return json.loads(row["payload"]) if row["payload"] else {"run_id": run_id, "status": row["status"]}

    def create_draft(self, state, payload):
        identity = [state.user_id, state.session_id, state.request_id, payload["kind"], payload["source_ids"]]
        draft_id = "DRAFT-" + digest(identity)[:24]
        payload = {**payload, "draft_id": draft_id}
        fingerprint = digest(payload)
        with self.connection() as conn, transaction(conn):
            session = conn.execute("SELECT 1 FROM sessions WHERE session_id=? AND expires_at>?",
                                   (state.session_id, int(time.time()))).fetchone()
            approval_trip = payload["facts"]["approval"]["trip_id"]
            approval_row = conn.execute("SELECT payload FROM mock_records WHERE kind='approvals' AND id=?",
                                        (approval_trip,)).fetchone()
            if not session or not approval_row or json.loads(approval_row[0])["status"] != "approved":
                raise StoreError("approval_required", 403)
            row = conn.execute("SELECT payload,request_hash FROM drafts WHERE draft_id=?", (draft_id,)).fetchone()
            if row:
                if row["request_hash"] != fingerprint:
                    raise StoreError("draft_idempotency_conflict", 409)
                return json.loads(row["payload"])
            conn.execute("INSERT INTO drafts VALUES (?,?,?,?,?)",
                         (draft_id, state.user_id, state.session_id, fingerprint, json.dumps(payload, ensure_ascii=False)))
        return payload

    def get_draft(self, session, draft_id):
        with self.connection() as conn:
            row = conn.execute("SELECT payload FROM drafts WHERE draft_id=? AND user_id=? AND session_id=?",
                               (draft_id, session["user_id"], session["session_id"])).fetchone()
        if row is None:
            raise StoreError("draft_not_found", 404)
        return json.loads(row[0])
