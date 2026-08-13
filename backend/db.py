"""SQLite access layer.

One shared connection guarded by a lock. Queries here are sub-millisecond local
reads, so holding the lock across them costs nothing and keeps the simulation
engine (an asyncio task) from racing the request handlers.
"""
from __future__ import annotations

import json
import sqlite3
import threading
from typing import Any

from backend.config import DB_PATH

_lock = threading.RLock()
_conn: sqlite3.Connection | None = None

SCHEMA = """
CREATE TABLE IF NOT EXISTS customers (
    id                   TEXT PRIMARY KEY,
    name                 TEXT NOT NULL,
    tier                 TEXT NOT NULL,
    annual_value         INTEGER NOT NULL,
    satisfaction         INTEGER NOT NULL,
    contract_renewal_days INTEGER NOT NULL,
    notes                TEXT NOT NULL DEFAULT ''
);

CREATE TABLE IF NOT EXISTS customer_history (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    customer_id TEXT NOT NULL REFERENCES customers(id),
    occurred_at TEXT NOT NULL,
    kind        TEXT NOT NULL,
    summary     TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS services (
    name        TEXT PRIMARY KEY,
    status      TEXT NOT NULL,
    latency_ms  INTEGER NOT NULL,
    error_rate  REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS logs (
    id       INTEGER PRIMARY KEY AUTOINCREMENT,
    logged_at TEXT NOT NULL,
    service  TEXT NOT NULL,
    level    TEXT NOT NULL,
    message  TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS tickets (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    customer_id TEXT NOT NULL,
    title       TEXT NOT NULL,
    priority    TEXT NOT NULL,
    status      TEXT NOT NULL DEFAULT 'open',
    created_at  TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS bug_reports (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    title        TEXT NOT NULL,
    root_cause   TEXT NOT NULL,
    severity     TEXT NOT NULL,
    proposed_fix TEXT NOT NULL,
    created_at   TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS tasks (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    assigned_to TEXT NOT NULL,
    description TEXT NOT NULL,
    priority    TEXT NOT NULL,
    status      TEXT NOT NULL DEFAULT 'pending',
    created_at  TEXT NOT NULL
);

-- Single-row global simulation state (§13).
CREATE TABLE IF NOT EXISTS company_state (
    id                  INTEGER PRIMARY KEY CHECK (id = 1),
    revenue             INTEGER NOT NULL,
    customer_count      INTEGER NOT NULL,
    active_issues       INTEGER NOT NULL,
    satisfaction        INTEGER NOT NULL,
    pending_tasks       INTEGER NOT NULL,
    reputation          INTEGER NOT NULL,
    investor_confidence INTEGER NOT NULL
);

-- Long-term agent memory (§8). Short-term memory lives in the run, not here.
CREATE TABLE IF NOT EXISTS agent_memory (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    agent      TEXT NOT NULL,
    subject    TEXT NOT NULL,
    content    TEXT NOT NULL,
    importance INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS runs (
    id         TEXT PRIMARY KEY,
    event_type TEXT NOT NULL,
    status     TEXT NOT NULL,
    started_at TEXT NOT NULL,
    ended_at   TEXT
);

-- Every visible thing that happened, in order. Drives the timeline replay.
CREATE TABLE IF NOT EXISTS run_events (
    id       INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id   TEXT NOT NULL REFERENCES runs(id),
    seq      INTEGER NOT NULL,
    at       TEXT NOT NULL,
    kind     TEXT NOT NULL,
    actor    TEXT,
    target   TEXT,
    payload  TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_run_events_run ON run_events(run_id, seq);
CREATE INDEX IF NOT EXISTS idx_history_customer ON customer_history(customer_id);
CREATE INDEX IF NOT EXISTS idx_logs_service ON logs(service);
CREATE INDEX IF NOT EXISTS idx_memory_agent ON agent_memory(agent, subject);
"""


def connect() -> sqlite3.Connection:
    global _conn
    with _lock:
        if _conn is None:
            _conn = sqlite3.connect(DB_PATH, check_same_thread=False)
            _conn.row_factory = sqlite3.Row
            _conn.execute("PRAGMA journal_mode=WAL")
            _conn.execute("PRAGMA foreign_keys=ON")
        return _conn


def query(sql: str, params: tuple = ()) -> list[dict[str, Any]]:
    with _lock:
        cur = connect().execute(sql, params)
        return [dict(r) for r in cur.fetchall()]


def query_one(sql: str, params: tuple = ()) -> dict[str, Any] | None:
    rows = query(sql, params)
    return rows[0] if rows else None


def execute(sql: str, params: tuple = ()) -> int:
    with _lock:
        conn = connect()
        cur = conn.execute(sql, params)
        conn.commit()
        return cur.lastrowid


def init_db(reset: bool = False) -> None:
    with _lock:
        conn = connect()
        conn.executescript(SCHEMA)
        conn.commit()
        if reset:
            for table in (
                "run_events", "runs", "tickets", "bug_reports",
                "tasks", "agent_memory", "customer_history", "logs",
                "customers", "services", "company_state",
            ):
                conn.execute(f"DELETE FROM {table}")
            conn.commit()
        seed()


def seed() -> None:
    """Populate the fictional company. Idempotent."""
    if query_one("SELECT id FROM company_state WHERE id = 1") is None:
        execute(
            """INSERT INTO company_state
               (id, revenue, customer_count, active_issues, satisfaction,
                pending_tasks, reputation, investor_confidence)
               VALUES (1, 2400000, 48, 0, 82, 0, 76, 71)"""
        )

    if not query("SELECT id FROM customers"):
        customers = [
            ("acme", "ACME Corporation", "enterprise", 120000, 64, 30,
             "Prefers fast support. Escalates quickly. Renewal imminent."),
            ("northwind", "Northwind Trading", "mid-market", 38000, 79, 190,
             "Steady account, low touch."),
            ("globex", "Globex Industries", "enterprise", 95000, 88, 145,
             "Expanding seat count next quarter."),
        ]
        for c in customers:
            execute(
                """INSERT INTO customers
                   (id, name, tier, annual_value, satisfaction,
                    contract_renewal_days, notes) VALUES (?,?,?,?,?,?,?)""", c)

        history = [
            ("acme", "2025-11-04", "incident", "Payment API timeout during checkout; resolved in 6h."),
            ("acme", "2026-02-18", "escalation", "Escalated slow support response to their VP of Ops."),
            ("acme", "2026-05-22", "expansion", "Added 40 seats; contract value rose to $120k/year."),
            ("acme", "2026-07-30", "sentiment", "Told CSM they are evaluating a competitor."),
            ("northwind", "2026-03-11", "incident", "Minor export bug, low severity."),
            ("globex", "2026-06-02", "expansion", "Signed a two-year renewal."),
        ]
        for h in history:
            execute(
                """INSERT INTO customer_history (customer_id, occurred_at, kind, summary)
                   VALUES (?,?,?,?)""", h)

    if not query("SELECT name FROM services"):
        services = [
            ("payment-api", "degraded", 4200, 0.14),
            ("auth-service", "healthy", 120, 0.001),
            ("web-frontend", "healthy", 240, 0.003),
            ("billing-worker", "degraded", 1800, 0.06),
            ("notification-service", "healthy", 95, 0.002),
        ]
        for s in services:
            execute("INSERT INTO services (name, status, latency_ms, error_rate) VALUES (?,?,?,?)", s)

    if not query("SELECT id FROM logs"):
        logs = [
            ("2026-08-13T09:38:11", "payment-api", "ERROR", "Upstream timeout after 5000ms calling processor gateway (txn 8841-ACME)"),
            ("2026-08-13T09:38:14", "payment-api", "ERROR", "Retry 1/1 failed: connection reset by peer"),
            ("2026-08-13T09:38:14", "payment-api", "WARN",  "Circuit breaker half-open, 14% of requests failing"),
            ("2026-08-13T09:39:02", "billing-worker", "ERROR", "Job payment.capture abandoned after 2 attempts (customer acme)"),
            ("2026-08-13T09:39:40", "payment-api", "ERROR", "Upstream timeout after 5000ms calling processor gateway (txn 8843-ACME)"),
            ("2026-08-13T09:40:05", "payment-api", "INFO",  "p99 latency 4.2s (baseline 380ms)"),
            ("2026-08-13T09:12:00", "auth-service", "INFO", "Token refresh volume nominal"),
            ("2026-08-13T08:55:31", "web-frontend", "WARN", "Checkout page bounce rate elevated"),
        ]
        for l in logs:
            execute("INSERT INTO logs (logged_at, service, level, message) VALUES (?,?,?,?)", l)

    if not query("SELECT id FROM agent_memory"):
        memories = [
            ("sales", "acme", "ACME is our second-largest account at $120k/year and renews in 30 days. They escalate fast and judge us on response speed.", 5),
            ("sales", "acme", "Their VP of Ops was already unhappy about support latency in February.", 4),
            ("developer", "payment-api", "The payment API has timed out under load before; last November it was an upstream gateway limit, not our code.", 4),
            ("ceo", "acme", "Losing ACME would cut annual revenue by 5% and spook the board before the renewal cycle.", 5),
            ("ceo", "policy", "Critical customer-facing incidents get a named owner and a same-day decision.", 3),
            ("investor", "revenue", "Board flagged concentration risk: the top three accounts are 10% of revenue.", 4),
            ("customer", "self", "We have been patient through one outage already this year. Patience is thin.", 3),
        ]
        for m in memories:
            execute(
                """INSERT INTO agent_memory (agent, subject, content, importance, created_at)
                   VALUES (?,?,?,?, datetime('now'))""", m)


def refresh_counters() -> dict[str, Any]:
    """Recompute the fact-based counters from the tables that own them.

    active_issues and pending_tasks are never asserted by an agent -- they are
    whatever the ticket and task tables actually say, so they cannot drift when
    a model forgets to decrement one.
    """
    open_tickets = query_one("SELECT COUNT(*) AS n FROM tickets WHERE status = 'open'")["n"]
    pending = query_one("SELECT COUNT(*) AS n FROM tasks WHERE status = 'pending'")["n"]
    execute("UPDATE company_state SET active_issues = ?, pending_tasks = ? WHERE id = 1",
            (open_tickets, pending))
    return get_company_state()


def get_company_state() -> dict[str, Any]:
    return query_one("SELECT * FROM company_state WHERE id = 1") or {}


def apply_state_delta(**deltas: int) -> dict[str, Any]:
    """Apply signed deltas to company state, clamping percentage fields to 0-100."""
    allowed = {"revenue", "customer_count", "satisfaction", "reputation", "investor_confidence"}
    clamped = {"satisfaction", "reputation", "investor_confidence"}
    state = get_company_state()
    for field, delta in deltas.items():
        if field not in allowed or not delta:
            continue
        value = state[field] + delta
        if field in clamped:
            value = max(0, min(100, value))
        else:
            value = max(0, value)
        execute(f"UPDATE company_state SET {field} = ? WHERE id = 1", (value,))
    return get_company_state()


def dump_json(value: Any) -> str:
    return json.dumps(value, default=str)
