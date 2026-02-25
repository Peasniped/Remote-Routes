"""SQLite database management for Remote Routes."""

import sqlite3
import os
from typing import Optional


DB_PATH = os.path.join(os.path.expanduser("~"), ".remote_routes.db")


def _get_conn() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


# keep the old public name around so existing imports still work
get_connection = _get_conn


def _column_exists(cursor, table: str, column: str) -> bool:
    """Check whether *column* already exists in *table*."""
    for row in cursor.execute(f"PRAGMA table_info({table})"):
        if row["name"] == column:
            return True
    return False


def init_db() -> None:
    with _get_conn() as conn:
        # ── users table ──────────────────────────────────────────────────
        conn.execute("""
            CREATE TABLE IF NOT EXISTS users (
                id           INTEGER PRIMARY KEY AUTOINCREMENT,
                display_name TEXT    NOT NULL,
                username     TEXT    NOT NULL,
                password     TEXT    NOT NULL DEFAULT ''
            )
        """)

        # ── connections table ─────────────────────────────────────────────
        conn.execute("""
            CREATE TABLE IF NOT EXISTS connections (
                id       INTEGER PRIMARY KEY AUTOINCREMENT,
                name     TEXT    NOT NULL,
                type     TEXT    NOT NULL CHECK(type IN ('SSH', 'RDP')),
                host     TEXT    NOT NULL,
                port     INTEGER NOT NULL,
                username TEXT    NOT NULL DEFAULT '',
                password TEXT    NOT NULL DEFAULT '',
                notes    TEXT    NOT NULL DEFAULT '',
                user_id  INTEGER REFERENCES users(id) ON DELETE SET NULL
            )
        """)

        # ── migration: add user_id to legacy databases ───────────────────
        if not _column_exists(conn, "connections", "user_id"):
            conn.execute(
                "ALTER TABLE connections ADD COLUMN user_id INTEGER"
                " REFERENCES users(id) ON DELETE SET NULL"
            )

        conn.commit()


# ─── Users CRUD ───────────────────────────────────────────────────────────────

def get_all_users() -> list[sqlite3.Row]:
    with _get_conn() as conn:
        return conn.execute(
            "SELECT * FROM users ORDER BY display_name COLLATE NOCASE"
        ).fetchall()


def get_user_by_id(user_id: int) -> Optional[sqlite3.Row]:
    with _get_conn() as conn:
        return conn.execute(
            "SELECT * FROM users WHERE id = ?", (user_id,)
        ).fetchone()


def add_user(display_name: str, username: str, password: str = "") -> int:
    with _get_conn() as conn:
        cur = conn.execute(
            "INSERT INTO users (display_name, username, password) VALUES (?, ?, ?)",
            (display_name, username, password),
        )
        conn.commit()
        return cur.lastrowid


def update_user(user_id: int, display_name: str, username: str,
                password: str = "") -> None:
    with _get_conn() as conn:
        conn.execute(
            "UPDATE users SET display_name=?, username=?, password=? WHERE id=?",
            (display_name, username, password, user_id),
        )
        conn.commit()


def delete_user(user_id: int) -> None:
    with _get_conn() as conn:
        conn.execute("DELETE FROM users WHERE id = ?", (user_id,))
        conn.commit()


# ─── Connections CRUD ─────────────────────────────────────────────────────────

def get_all_connections() -> list[sqlite3.Row]:
    with _get_conn() as conn:
        return conn.execute(
            "SELECT * FROM connections ORDER BY name COLLATE NOCASE"
        ).fetchall()


def get_connection_by_id(conn_id: int) -> Optional[sqlite3.Row]:
    with _get_conn() as conn:
        return conn.execute(
            "SELECT * FROM connections WHERE id = ?", (conn_id,)
        ).fetchone()


def add_connection(
    name: str,
    type: str,
    host: str,
    port: int,
    username: str = "",
    password: str = "",
    notes: str = "",
    user_id: int | None = None,
) -> int:
    with _get_conn() as conn:
        cur = conn.execute(
            "INSERT INTO connections"
            " (name, type, host, port, username, password, notes, user_id)"
            " VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (name, type, host, port, username, password, notes, user_id),
        )
        conn.commit()
        return cur.lastrowid


def update_connection(
    conn_id: int,
    name: str,
    type: str,
    host: str,
    port: int,
    username: str = "",
    password: str = "",
    notes: str = "",
    user_id: int | None = None,
) -> None:
    with _get_conn() as conn:
        conn.execute(
            "UPDATE connections SET name=?, type=?, host=?, port=?,"
            " username=?, password=?, notes=?, user_id=? WHERE id=?",
            (name, type, host, port, username, password, notes, user_id, conn_id),
        )
        conn.commit()


def delete_connection(conn_id: int) -> None:
    with _get_conn() as conn:
        conn.execute("DELETE FROM connections WHERE id = ?", (conn_id,))
        conn.commit()


def get_effective_credentials(conn_id: int) -> tuple[str, str]:
    """Return (username, password) using the linked user when available."""
    rec = get_connection_by_id(conn_id)
    if rec is None:
        return ("", "")
    if rec["user_id"]:
        user = get_user_by_id(rec["user_id"])
        if user:
            return (user["username"], user["password"])
    return (rec["username"], rec["password"])
