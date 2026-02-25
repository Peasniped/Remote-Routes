"""SQLite database management for Remote Routes."""

import sqlite3
import os
from typing import Optional


DB_PATH = os.path.join(os.path.expanduser("~"), ".remote_routes.db")


def get_connection() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db() -> None:
    with get_connection() as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS connections (
                id       INTEGER PRIMARY KEY AUTOINCREMENT,
                name     TEXT    NOT NULL,
                type     TEXT    NOT NULL CHECK(type IN ('SSH', 'RDP')),
                host     TEXT    NOT NULL,
                port     INTEGER NOT NULL,
                username TEXT    NOT NULL,
                password TEXT    NOT NULL DEFAULT '',
                notes    TEXT    NOT NULL DEFAULT ''
            )
        """)
        conn.commit()


def get_all_connections() -> list[sqlite3.Row]:
    with get_connection() as conn:
        return conn.execute(
            "SELECT * FROM connections ORDER BY name COLLATE NOCASE"
        ).fetchall()


def get_connection_by_id(conn_id: int) -> Optional[sqlite3.Row]:
    with get_connection() as conn:
        return conn.execute(
            "SELECT * FROM connections WHERE id = ?", (conn_id,)
        ).fetchone()


def add_connection(
    name: str,
    conn_type: str,
    host: str,
    port: int,
    username: str,
    password: str = "",
    notes: str = "",
) -> int:
    with get_connection() as conn:
        cursor = conn.execute(
            "INSERT INTO connections (name, type, host, port, username, password, notes)"
            " VALUES (?, ?, ?, ?, ?, ?, ?)",
            (name, conn_type, host, port, username, password, notes),
        )
        conn.commit()
        return cursor.lastrowid


def update_connection(
    conn_id: int,
    name: str,
    conn_type: str,
    host: str,
    port: int,
    username: str,
    password: str = "",
    notes: str = "",
) -> None:
    with get_connection() as conn:
        conn.execute(
            "UPDATE connections SET name=?, type=?, host=?, port=?, username=?,"
            " password=?, notes=? WHERE id=?",
            (name, conn_type, host, port, username, password, notes, conn_id),
        )
        conn.commit()


def delete_connection(conn_id: int) -> None:
    with get_connection() as conn:
        conn.execute("DELETE FROM connections WHERE id = ?", (conn_id,))
        conn.commit()
