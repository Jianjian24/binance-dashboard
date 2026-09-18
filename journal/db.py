from __future__ import annotations

import sqlite3
import threading
from pathlib import Path
from typing import Any, Iterable, Optional

DATA_DIR = Path(__file__).resolve().parent / "data"
DB_PATH = DATA_DIR / "ledger.sqlite"

_local = threading.local()

SCHEMA = """
PRAGMA journal_mode=WAL;
PRAGMA foreign_keys=ON;

CREATE TABLE IF NOT EXISTS fills (
    trade_id INTEGER PRIMARY KEY,
    order_id INTEGER,
    client_order_id TEXT,
    symbol TEXT NOT NULL,
    side TEXT NOT NULL,
    position_side TEXT NOT NULL DEFAULT 'BOTH',
    price REAL NOT NULL,
    qty REAL NOT NULL,
    quote_qty REAL,
    realized_pnl REAL NOT NULL DEFAULT 0,
    commission REAL NOT NULL DEFAULT 0,
    commission_asset TEXT,
    maker INTEGER NOT NULL DEFAULT 0,
    time_ms INTEGER NOT NULL,
    strategy_tag TEXT NOT NULL DEFAULT 'OTHER'
);
CREATE INDEX IF NOT EXISTS idx_fills_symbol_time ON fills(symbol, time_ms);
CREATE INDEX IF NOT EXISTS idx_fills_time ON fills(time_ms);
CREATE INDEX IF NOT EXISTS idx_fills_tag ON fills(strategy_tag);
CREATE INDEX IF NOT EXISTS idx_fills_symbol_order ON fills(symbol, order_id);

CREATE TABLE IF NOT EXISTS income (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    time_ms INTEGER NOT NULL,
    symbol TEXT,
    income_type TEXT NOT NULL,
    income REAL NOT NULL,
    asset TEXT,
    tran_id TEXT,
    UNIQUE(tran_id, income_type, time_ms)
);
CREATE INDEX IF NOT EXISTS idx_income_time ON income(time_ms);
CREATE INDEX IF NOT EXISTS idx_income_type ON income(income_type);

CREATE TABLE IF NOT EXISTS roundtrips (
    id TEXT PRIMARY KEY,
    symbol TEXT NOT NULL,
    side TEXT NOT NULL,
    open_time_ms INTEGER NOT NULL,
    close_time_ms INTEGER,
    qty REAL NOT NULL,
    entry_price REAL NOT NULL,
    exit_price REAL,
    realized_pnl REAL NOT NULL DEFAULT 0,
    commission REAL NOT NULL DEFAULT 0,
    net_pnl REAL NOT NULL DEFAULT 0,
    hold_ms INTEGER,
    status TEXT NOT NULL,
    tags TEXT NOT NULL DEFAULT 'OTHER',
    fill_ids TEXT NOT NULL DEFAULT ''
);
CREATE INDEX IF NOT EXISTS idx_rt_close ON roundtrips(close_time_ms);
CREATE INDEX IF NOT EXISTS idx_rt_symbol ON roundtrips(symbol);
CREATE INDEX IF NOT EXISTS idx_rt_status ON roundtrips(status);

CREATE TABLE IF NOT EXISTS day_notes (
    day TEXT PRIMARY KEY,
    body TEXT NOT NULL DEFAULT '',
    updated_ms INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS sync_state (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
"""


def connect(path: Optional[Path] = None) -> sqlite3.Connection:
    db_path = path or DB_PATH
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(db_path), check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.isolation_level = None  # autocommit: avoid stale snapshots across requests
    conn.executescript(SCHEMA)
    return conn


def get_conn() -> sqlite3.Connection:
    conn = getattr(_local, "conn", None)
    if conn is None:
        conn = connect()
        _local.conn = conn
    return conn


def fetchall(sql: str, params: Iterable[Any] = ()) -> list[dict[str, Any]]:
    cur = get_conn().execute(sql, tuple(params))
    return [dict(row) for row in cur.fetchall()]


def fetchone(sql: str, params: Iterable[Any] = ()) -> Optional[dict[str, Any]]:
    cur = get_conn().execute(sql, tuple(params))
    row = cur.fetchone()
    return dict(row) if row else None


def execute(sql: str, params: Iterable[Any] = ()) -> None:
    conn = get_conn()
    conn.execute(sql, tuple(params))
    conn.commit()


def executemany(sql: str, rows: Iterable[Iterable[Any]]) -> int:
    conn = get_conn()
    cur = conn.executemany(sql, list(rows))
    conn.commit()
    return cur.rowcount or 0


def get_state(key: str, default: str = "") -> str:
    row = fetchone("SELECT value FROM sync_state WHERE key = ?", (key,))
    return str(row["value"]) if row else default


def set_state(key: str, value: str) -> None:
    execute(
        "INSERT INTO sync_state(key, value) VALUES(?, ?) "
        "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
        (key, value),
    )
