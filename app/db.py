from __future__ import annotations

import json
import sqlite3
from pathlib import Path

from app.config import settings

SCHEMA = """
CREATE TABLE IF NOT EXISTS records (
    id TEXT PRIMARY KEY,
    customer_name TEXT NOT NULL,
    email TEXT NOT NULL,
    phone TEXT NOT NULL,
    amount_paise INTEGER NOT NULL,
    record_type TEXT NOT NULL,
    error_code TEXT,
    error_description TEXT,
    notes TEXT,
    opted_out INTEGER NOT NULL DEFAULT 0,
    true_cause TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS runs (
    id TEXT PRIMARY KEY,
    policy TEXT NOT NULL,
    started_at TEXT NOT NULL,
    finished_at TEXT,
    at_risk_paise INTEGER DEFAULT 0,
    recovered_paise INTEGER DEFAULT 0,
    diagnosis_correct INTEGER DEFAULT 0,
    diagnosis_total INTEGER DEFAULT 0,
    illegal_contacts INTEGER DEFAULT 0
);

CREATE TABLE IF NOT EXISTS decisions (
    id TEXT PRIMARY KEY,
    run_id TEXT NOT NULL,
    record_id TEXT NOT NULL,
    policy TEXT NOT NULL,
    diagnosed_cause TEXT,
    diagnosis_confidence REAL,
    diagnosis_rationale TEXT,
    proposed_action TEXT,
    proposed_channel TEXT,
    message_body TEXT,
    supervisor_allowed INTEGER,
    supervisor_status TEXT,
    rule_ids TEXT,
    supervisor_reason TEXT,
    razorpay_link_id TEXT,
    razorpay_short_url TEXT,
    outcome TEXT NOT NULL,
    recovered_paise INTEGER NOT NULL DEFAULT 0,
    action_match INTEGER,
    created_at TEXT NOT NULL,
    FOREIGN KEY (run_id) REFERENCES runs(id),
    FOREIGN KEY (record_id) REFERENCES records(id)
);

CREATE TABLE IF NOT EXISTS webhook_events (
    id TEXT PRIMARY KEY,
    event TEXT,
    payment_link_id TEXT,
    signature_ok INTEGER DEFAULT 0,
    payload TEXT,
    created_at TEXT NOT NULL
);
"""


def connect() -> sqlite3.Connection:
    path = Path(settings.database_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA journal_mode=WAL")
    return conn


def init_db() -> None:
    conn = connect()
    conn.executescript(SCHEMA)
    conn.commit()
    conn.close()


def row_to_dict(row: sqlite3.Row | None) -> dict | None:
    if row is None:
        return None
    d = dict(row)
    if "rule_ids" in d and isinstance(d["rule_ids"], str):
        try:
            d["rule_ids"] = json.loads(d["rule_ids"])
        except json.JSONDecodeError:
            pass
    return d
