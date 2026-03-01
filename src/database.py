"""SQLite database management for Remote Routes."""

import sqlite3
import os
from typing import Optional


_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DB_PATH = os.path.join(_PROJECT_ROOT, "instance", ".remote_routes.db")


def _get_conn() -> sqlite3.Connection:
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
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

        # ── migration: add screenshot blob ────────────────────────────────
        if not _column_exists(conn, "connections", "screenshot"):
            conn.execute(
                "ALTER TABLE connections ADD COLUMN screenshot BLOB"
            )

        # ── settings table (key-value) ────────────────────────────────────
        conn.execute("""
            CREATE TABLE IF NOT EXISTS settings (
                key   TEXT PRIMARY KEY,
                value TEXT NOT NULL DEFAULT ''
            )
        """)

        # ── active sessions (survive app restarts) ────────────────────────
        conn.execute("""
            CREATE TABLE IF NOT EXISTS active_sessions (
                id      INTEGER PRIMARY KEY AUTOINCREMENT,
                conn_id INTEGER NOT NULL,
                hwnd    INTEGER NOT NULL DEFAULT 0,
                tag     TEXT    NOT NULL DEFAULT '',
                FOREIGN KEY (conn_id) REFERENCES connections(id) ON DELETE CASCADE
            )
        """)

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


def save_screenshot(conn_id: int, png_bytes: bytes) -> None:
    """Store a PNG screenshot blob for the given connection."""
    with _get_conn() as conn:
        conn.execute(
            "UPDATE connections SET screenshot = ? WHERE id = ?",
            (sqlite3.Binary(png_bytes), conn_id),
        )
        conn.commit()


def get_screenshot(conn_id: int) -> Optional[bytes]:
    """Return the stored PNG screenshot blob, or None."""
    with _get_conn() as conn:
        row = conn.execute(
            "SELECT screenshot FROM connections WHERE id = ?", (conn_id,)
        ).fetchone()
        if row and row["screenshot"]:
            return bytes(row["screenshot"])
    return None


# ─── Settings ─────────────────────────────────────────────────────────────────

_SETTING_DEFAULTS: dict[str, str] = {
    "show_search_bar":      "1",
    "screenshot_enabled":   "1",
    "screenshot_interval":  "30",
    "show_protocol_badge":  "1",
}


def get_setting(key: str) -> str:
    """Return the value for *key*, falling back to the built-in default."""
    with _get_conn() as conn:
        row = conn.execute(
            "SELECT value FROM settings WHERE key = ?", (key,)
        ).fetchone()
        if row:
            return row["value"]
    return _SETTING_DEFAULTS.get(key, "")


def set_setting(key: str, value: str) -> None:
    """Insert or update a setting."""
    with _get_conn() as conn:
        conn.execute(
            "INSERT INTO settings (key, value) VALUES (?, ?)"
            " ON CONFLICT(key) DO UPDATE SET value = excluded.value",
            (key, value),
        )
        conn.commit()


# ─── Active sessions ──────────────────────────────────────────────────────────

def save_session(conn_id: int, hwnd: int, tag: str) -> None:
    """Record an active window so it can be reattached after restart."""
    with _get_conn() as conn:
        conn.execute(
            "INSERT INTO active_sessions (conn_id, hwnd, tag) VALUES (?, ?, ?)",
            (conn_id, hwnd, tag),
        )
        conn.commit()


def get_sessions() -> list[sqlite3.Row]:
    """Return all persisted active sessions."""
    with _get_conn() as conn:
        return conn.execute("SELECT * FROM active_sessions").fetchall()


def clear_sessions(conn_id: int | None = None) -> None:
    """Remove persisted sessions.  If *conn_id* given, only for that connection."""
    with _get_conn() as conn:
        if conn_id is not None:
            conn.execute(
                "DELETE FROM active_sessions WHERE conn_id = ?", (conn_id,)
            )
        else:
            conn.execute("DELETE FROM active_sessions")
        conn.commit()


def remove_session_by_hwnd(hwnd: int) -> None:
    """Remove a single session row by HWND."""
    with _get_conn() as conn:
        conn.execute("DELETE FROM active_sessions WHERE hwnd = ?", (hwnd,))
        conn.commit()
