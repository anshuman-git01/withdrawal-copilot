"""Per-browser session state and analytics events in SQLite (stdlib only)."""
from __future__ import annotations

import json
import os
import sqlite3
import threading
import time
import uuid
from collections import Counter

from .engine.models import demo_profile, demo_request, profile_to_dict, request_to_dict

DB_PATH = os.getenv("DB_PATH", os.path.join(os.path.dirname(os.path.dirname(__file__)), "data", "app.db"))
_lock = threading.Lock()

EVENTS = [
    "withdrawal_started", "amount_entered", "reason_selected", "materiality_triggered", "impact_viewed",
    "portfolio_impact_viewed", "goal_impact_viewed", "source_comparison_viewed", "borrow_comparison_viewed",
    "why_opened", "behaviour_check_triggered", "behaviour_check_continued", "withdrawal_modified",
    "withdrawal_deferred", "decision_completed", "recovery_plan_viewed", "recovery_scenario_selected",
    "funding_plan_chosen", "copilot_asked", "copilot_fallback",
]


def _conn():
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    c = sqlite3.connect(DB_PATH, check_same_thread=False)
    c.execute("CREATE TABLE IF NOT EXISTS sessions (sid TEXT PRIMARY KEY, state TEXT, updated REAL)")
    c.execute("CREATE TABLE IF NOT EXISTS events (id INTEGER PRIMARY KEY AUTOINCREMENT, sid TEXT, attempt TEXT,"
              " name TEXT, props TEXT, ts REAL)")
    return c


def new_state() -> dict:
    """The exact demo starting state from the brief."""
    return {
        "profile": profile_to_dict(demo_profile()),
        "request": request_to_dict(demo_request()),
        "simulate_behaviour": False,
        "plan": None,  # user-built funding allocations {source: rupees}
        "route": None,  # "sell" | "borrow" once the user picks one
        "decision": None,
        "attempt": None,
        "provider": None,
        "copilot_log": [],
        "first_amount": None,
    }


def new_sid() -> str:
    return uuid.uuid4().hex


def load(sid: str) -> dict:
    with _lock, _conn() as c:
        row = c.execute("SELECT state FROM sessions WHERE sid=?", (sid,)).fetchone()
    if not row:
        return new_state()
    state = new_state()
    state.update(json.loads(row[0]))
    return state


def save(sid: str, state: dict) -> None:
    with _lock, _conn() as c:
        c.execute("INSERT OR REPLACE INTO sessions (sid, state, updated) VALUES (?,?,?)",
                  (sid, json.dumps(state), time.time()))


def track(sid: str, state: dict, name: str, **props) -> None:
    with _lock, _conn() as c:
        c.execute("INSERT INTO events (sid, attempt, name, props, ts) VALUES (?,?,?,?,?)",
                  (sid, state.get("attempt"), name, json.dumps(props), time.time()))


def metrics(sid: str = None) -> dict:
    with _lock, _conn() as c:
        q = "SELECT sid, attempt, name, props, ts FROM events"
        rows = c.execute(q + (" WHERE sid=?" if sid else "") + " ORDER BY id DESC", (sid,) if sid else ()).fetchall()
    counts = Counter(r[2] for r in rows)
    by_attempt = {}
    for s, attempt, name, _, _ in rows:
        if attempt:
            by_attempt.setdefault(attempt, set()).add(name)
    significant = [a for a, names in by_attempt.items() if "materiality_triggered" in names]
    with_context = [a for a in significant
                    if by_attempt[a] & {"impact_viewed"} and "decision_completed" in by_attempt[a]]
    rate = (len(with_context) / len(significant) * 100) if significant else None
    return {
        "counts": [(e, counts.get(e, 0)) for e in EVENTS],
        "significant_attempts": len(significant),
        "completed_with_context": len(with_context),
        "north_star": rate,
        "recent": [{"name": r[2], "props": json.loads(r[3] or "{}"), "ts": time.strftime("%H:%M:%S", time.localtime(r[4]))}
                   for r in rows[:40]],
    }


def clear_events(sid: str) -> None:
    with _lock, _conn() as c:
        c.execute("DELETE FROM events WHERE sid=?", (sid,))
