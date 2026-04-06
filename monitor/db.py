import sqlite3
import time
from pathlib import Path

DB_DIR = Path.home() / "Library" / "Application Support" / "mac-monitor"
DB_PATH = DB_DIR / "metrics.db"
RETENTION_SECONDS = 86400  # 24 hours


def _conn():
    return sqlite3.connect(DB_PATH)


def init_db():
    DB_DIR.mkdir(parents=True, exist_ok=True)
    with _conn() as c:
        c.execute("""
            CREATE TABLE IF NOT EXISTS metrics (
                id         INTEGER PRIMARY KEY,
                ts         INTEGER NOT NULL,
                cpu        REAL,
                mem_pct    REAL,
                mem_used   REAL,
                mem_total  REAL,
                disk_pct   REAL,
                disk_used  REAL,
                disk_total REAL,
                gpu        REAL
            )
        """)
        c.execute("CREATE INDEX IF NOT EXISTS idx_ts ON metrics(ts)")
        # Migrate: add gpu column if it doesn't exist yet
        try:
            c.execute("ALTER TABLE metrics ADD COLUMN gpu REAL")
        except Exception:
            pass


def insert_sample(cpu, mem_pct, mem_used, mem_total, disk_pct, disk_used, disk_total, gpu=None):
    now = int(time.time())
    cutoff = now - RETENTION_SECONDS
    with _conn() as c:
        c.execute(
            "INSERT INTO metrics "
            "(ts, cpu, mem_pct, mem_used, mem_total, disk_pct, disk_used, disk_total, gpu) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (now, cpu, mem_pct, mem_used, mem_total, disk_pct, disk_used, disk_total, gpu),
        )
        c.execute("DELETE FROM metrics WHERE ts < ?", (cutoff,))


def get_history(window_seconds=3600):
    cutoff = int(time.time()) - min(window_seconds, RETENTION_SECONDS)
    with _conn() as c:
        c.row_factory = sqlite3.Row
        rows = c.execute(
            "SELECT ts, cpu, mem_pct, gpu FROM metrics WHERE ts >= ? ORDER BY ts ASC",
            (cutoff,),
        ).fetchall()
    return [dict(r) for r in rows]
