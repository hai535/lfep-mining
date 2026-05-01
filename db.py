"""SQLite helpers for the LFep mining backend.

No SQLAlchemy: raw sqlite3 with a thread-local connection. The schema is
created on import if missing.

Tables:
  questions                  — pre-seeded 100 Q+A
  streaks                    — per-address streak + lifetime stats
  consumed_session_nonces    — replay prevention for /api/question/submit
"""
from __future__ import annotations

import os
import sqlite3
import threading
import time
from contextlib import contextmanager

DB_PATH = os.environ.get("LFEP_DB", "/root/lfep_mining/lfep.db")

_local = threading.local()

SCHEMA = """
CREATE TABLE IF NOT EXISTS questions (
  id        INTEGER PRIMARY KEY,
  content   TEXT NOT NULL,
  answer    TEXT NOT NULL,
  difficulty INTEGER DEFAULT 1
);

CREATE TABLE IF NOT EXISTS streaks (
  address          TEXT PRIMARY KEY,
  current_streak   INTEGER NOT NULL DEFAULT 0,
  total_correct    INTEGER NOT NULL DEFAULT 0,
  total_attempts   INTEGER NOT NULL DEFAULT 0,
  total_earned_wei TEXT    NOT NULL DEFAULT '0',
  updated_at       INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS consumed_session_nonces (
  nonce       TEXT PRIMARY KEY,
  consumed_at INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_consumed_at ON consumed_session_nonces(consumed_at);

CREATE TABLE IF NOT EXISTS submissions (
  id              INTEGER PRIMARY KEY AUTOINCREMENT,
  address         TEXT    NOT NULL,
  question_id     INTEGER NOT NULL,
  is_correct      INTEGER NOT NULL,
  bonus_triggered INTEGER NOT NULL DEFAULT 0,
  amount_wei      TEXT    NOT NULL,
  streak_after    INTEGER NOT NULL DEFAULT 0,
  created_at      INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_subs_created ON submissions(created_at DESC);
"""


def get_conn() -> sqlite3.Connection:
    conn = getattr(_local, "conn", None)
    if conn is None:
        conn = sqlite3.connect(DB_PATH, isolation_level=None, check_same_thread=False)
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA synchronous=NORMAL")
        conn.row_factory = sqlite3.Row
        _local.conn = conn
    return conn


def init_db() -> None:
    conn = get_conn()
    conn.executescript(SCHEMA)


@contextmanager
def cursor():
    conn = get_conn()
    cur = conn.cursor()
    try:
        yield cur
    finally:
        cur.close()


# ---------- questions ----------

def question_count() -> int:
    with cursor() as c:
        c.execute("SELECT COUNT(*) FROM questions")
        return c.fetchone()[0]


def random_question() -> sqlite3.Row | None:
    with cursor() as c:
        c.execute(
            "SELECT id, content, answer, difficulty FROM questions ORDER BY RANDOM() LIMIT 1"
        )
        return c.fetchone()


def random_question_by_difficulty(difficulties: list[int]) -> sqlite3.Row | None:
    """Pick a random question whose difficulty is in `difficulties`.
    Falls back to ANY question if no questions exist at the requested level."""
    if not difficulties:
        return random_question()
    placeholders = ",".join("?" * len(difficulties))
    with cursor() as c:
        c.execute(
            f"SELECT id, content, answer, difficulty FROM questions "
            f"WHERE difficulty IN ({placeholders}) ORDER BY RANDOM() LIMIT 1",
            tuple(difficulties),
        )
        row = c.fetchone()
    return row or random_question()


def get_question(qid: int) -> sqlite3.Row | None:
    with cursor() as c:
        c.execute(
            "SELECT id, content, answer, difficulty FROM questions WHERE id=?",
            (qid,),
        )
        return c.fetchone()


def insert_question(qid: int, content: str, answer: str, difficulty: int = 1) -> None:
    with cursor() as c:
        c.execute(
            "INSERT OR REPLACE INTO questions (id, content, answer, difficulty) VALUES (?, ?, ?, ?)",
            (qid, content, answer, difficulty),
        )


# ---------- streaks ----------

def get_streak_row(address: str) -> sqlite3.Row | None:
    with cursor() as c:
        c.execute(
            "SELECT * FROM streaks WHERE address=?",
            (address.lower(),),
        )
        return c.fetchone()


def upsert_streak(
    address: str,
    new_streak: int,
    is_correct: bool,
    earned_wei_delta: int,
) -> None:
    """Read-modify-write within a transaction. Big-integer math in Python because
    SQLite INTEGER tops out at 2^63-1 and our wei values exceed that."""
    addr = address.lower()
    now = int(time.time())
    conn = get_conn()
    cur = conn.cursor()
    try:
        cur.execute("BEGIN IMMEDIATE")
        cur.execute(
            "SELECT total_correct, total_attempts, total_earned_wei FROM streaks WHERE address=?",
            (addr,),
        )
        row = cur.fetchone()
        if row is None:
            new_total_correct = 1 if is_correct else 0
            new_total_attempts = 1
            new_total_wei = earned_wei_delta
            cur.execute(
                """INSERT INTO streaks (address, current_streak, total_correct,
                       total_attempts, total_earned_wei, updated_at)
                   VALUES (?, ?, ?, ?, ?, ?)""",
                (addr, new_streak, new_total_correct, new_total_attempts,
                 str(new_total_wei), now),
            )
        else:
            try:
                prev_wei = int(row["total_earned_wei"])
            except (TypeError, ValueError):
                prev_wei = 0
            cur.execute(
                """UPDATE streaks SET current_streak=?, total_correct=?,
                       total_attempts=?, total_earned_wei=?, updated_at=?
                   WHERE address=?""",
                (
                    new_streak,
                    row["total_correct"] + (1 if is_correct else 0),
                    row["total_attempts"] + 1,
                    str(prev_wei + earned_wei_delta),
                    now,
                    addr,
                ),
            )
        cur.execute("COMMIT")
    except Exception:
        cur.execute("ROLLBACK")
        raise
    finally:
        cur.close()


def leaderboard(limit: int = 20) -> list[sqlite3.Row]:
    with cursor() as c:
        # Sorting TEXT bigints lexicographically requires same length, so we
        # cast to INTEGER (sqlite handles up to 2**63 — our biggest single
        # earnings would be ~10^25, overflowing). Use length-aware sort.
        c.execute(
            """
            SELECT address, current_streak, total_correct, total_attempts, total_earned_wei
            FROM streaks
            ORDER BY LENGTH(total_earned_wei) DESC, total_earned_wei DESC
            LIMIT ?
            """,
            (limit,),
        )
        return c.fetchall()


# ---------- submissions (activity feed) ----------

def insert_submission(
    address: str,
    question_id: int,
    is_correct: bool,
    bonus_triggered: bool,
    amount_wei: int,
    streak_after: int,
) -> None:
    with cursor() as c:
        c.execute(
            """INSERT INTO submissions
                 (address, question_id, is_correct, bonus_triggered,
                  amount_wei, streak_after, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (
                address.lower(),
                question_id,
                1 if is_correct else 0,
                1 if bonus_triggered else 0,
                str(amount_wei),
                streak_after,
                int(time.time()),
            ),
        )


def recent_submissions(limit: int = 20) -> list[sqlite3.Row]:
    with cursor() as c:
        c.execute(
            """SELECT address, question_id, is_correct, bonus_triggered,
                      amount_wei, streak_after, created_at
               FROM submissions
               ORDER BY created_at DESC
               LIMIT ?""",
            (limit,),
        )
        return c.fetchall()


def total_miners() -> int:
    with cursor() as c:
        c.execute("SELECT COUNT(*) FROM streaks")
        return c.fetchone()[0]


def address_rank(address: str) -> int | None:
    """Returns 1-indexed rank by total_earned_wei, or None if address has no record."""
    addr = address.lower()
    with cursor() as c:
        c.execute("SELECT total_earned_wei FROM streaks WHERE address=?", (addr,))
        row = c.fetchone()
        if row is None:
            return None
        my_wei = int(row["total_earned_wei"] or 0)
        c.execute(
            """SELECT COUNT(*) FROM streaks
               WHERE LENGTH(total_earned_wei) > LENGTH(?) OR
                     (LENGTH(total_earned_wei) = LENGTH(?) AND total_earned_wei > ?)""",
            (str(my_wei), str(my_wei), str(my_wei)),
        )
        return c.fetchone()[0] + 1


# ---------- consumed nonces (replay prevention) ----------

def consume_session_nonce(nonce: str) -> bool:
    """Returns True if nonce was newly inserted (legit), False if it was a replay."""
    now = int(time.time())
    with cursor() as c:
        try:
            c.execute(
                "INSERT INTO consumed_session_nonces (nonce, consumed_at) VALUES (?, ?)",
                (nonce, now),
            )
            return True
        except sqlite3.IntegrityError:
            return False


def cleanup_old_nonces(older_than_seconds: int = 3600) -> int:
    cutoff = int(time.time()) - older_than_seconds
    with cursor() as c:
        c.execute(
            "DELETE FROM consumed_session_nonces WHERE consumed_at < ?",
            (cutoff,),
        )
        return c.rowcount


# ---------- aggregate stats for /api/health ----------

def total_distributed_wei() -> int:
    with cursor() as c:
        c.execute("SELECT total_earned_wei FROM streaks")
        rows = c.fetchall()
    total = 0
    for r in rows:
        try:
            total += int(r["total_earned_wei"])
        except (TypeError, ValueError):
            pass
    return total


def total_attempts() -> int:
    with cursor() as c:
        c.execute("SELECT COALESCE(SUM(total_attempts), 0) FROM streaks")
        return c.fetchone()[0]


if __name__ == "__main__":
    init_db()
    print(f"DB: {DB_PATH}")
    print(f"questions: {question_count()}")
    print(f"attempts:  {total_attempts()}")
