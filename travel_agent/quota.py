import sqlite3
from contextlib import closing
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo


class DailyLimitReached(Exception):
    pass


class DailyBudget:
    def __init__(self, path, limit):
        self.path = str(path)
        self.limit = limit
        Path(self.path).parent.mkdir(parents=True, exist_ok=True)
        with closing(sqlite3.connect(self.path)) as conn, conn:
            conn.execute("CREATE TABLE IF NOT EXISTS llm_daily_usage ("
                         "model_id TEXT NOT NULL, quota_day TEXT NOT NULL, attempts INTEGER NOT NULL,"
                         "PRIMARY KEY(model_id,quota_day))")

    def reserve(self, model_id, now=None):
        day = (now or datetime.now(ZoneInfo("America/Los_Angeles"))).astimezone(ZoneInfo("America/Los_Angeles")).date().isoformat()
        with closing(sqlite3.connect(self.path, timeout=10)) as conn, conn:
            conn.execute("BEGIN IMMEDIATE")
            row = conn.execute("SELECT attempts FROM llm_daily_usage WHERE model_id=? AND quota_day=?", (model_id, day)).fetchone()
            used = row[0] if row else 0
            if used >= self.limit:
                raise DailyLimitReached()
            conn.execute("INSERT INTO llm_daily_usage VALUES (?,?,1) ON CONFLICT(model_id,quota_day)"
                         " DO UPDATE SET attempts=attempts+1", (model_id, day))
            return used + 1
