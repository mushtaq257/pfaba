from __future__ import annotations

import sqlite3
from contextlib import closing
from pathlib import Path
from typing import Any, Sequence

import psycopg
from psycopg.rows import dict_row

from backend.app.config import get_settings

DB_PATH = Path(__file__).resolve().parent / "data" / "finance.db"


class _PostgresConnection:
    def __init__(self, connection: psycopg.Connection) -> None:
        self._connection = connection

    def execute(self, query: str, parameters: Sequence[Any] = ()) -> Any:
        return self._connection.execute(query.replace("?", "%s"), parameters)

    def commit(self) -> None:
        self._connection.commit()

    def close(self) -> None:
        self._connection.close()


def get_connection() -> sqlite3.Connection | _PostgresConnection:
    database_url = (get_settings().database_url or "").strip()
    if database_url:
        if database_url.startswith("postgres://"):
            database_url = "postgresql://" + database_url[len("postgres://"):]
        if not database_url.startswith("postgresql://"):
            raise ValueError("DATABASE_URL must use the PostgreSQL URL scheme.")
        connection = psycopg.connect(database_url, row_factory=dict_row)
        return _PostgresConnection(connection)

    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db() -> None:
    use_postgres = bool((get_settings().database_url or "").strip())
    primary_key = (
        "BIGSERIAL PRIMARY KEY"
        if use_postgres
        else "INTEGER PRIMARY KEY AUTOINCREMENT"
    )
    float_type = "DOUBLE PRECISION" if use_postgres else "REAL"
    with closing(get_connection()) as conn:
        conn.execute(
            f"""
            CREATE TABLE IF NOT EXISTS profiles (
                id {primary_key},
                session_id TEXT UNIQUE,
                income {float_type} DEFAULT 0,
                currency TEXT DEFAULT 'USD',
                location TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
            """
        )
        conn.execute(
            f"""
            CREATE TABLE IF NOT EXISTS transactions (
                id {primary_key},
                session_id TEXT,
                description TEXT,
                amount {float_type},
                currency TEXT,
                category TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (session_id) REFERENCES profiles(session_id)
            )
            """
        )
        conn.execute(
            f"""
            CREATE TABLE IF NOT EXISTS goals (
                id {primary_key},
                session_id TEXT,
                name TEXT,
                target_amount {float_type},
                saved_amount {float_type},
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (session_id) REFERENCES profiles(session_id)
            )
            """
        )
        conn.execute(
            f"""
            CREATE TABLE IF NOT EXISTS historical_permissions (
                session_id TEXT PRIMARY KEY,
                can_edit_previous_month INTEGER NOT NULL DEFAULT 0,
                can_delete_previous_month INTEGER NOT NULL DEFAULT 0,
                can_clear_previous_month INTEGER NOT NULL DEFAULT 0,
                updated_by TEXT,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
            """
        )
        conn.execute(
            f"""
            CREATE TABLE IF NOT EXISTS admin_audit_log (
                id {primary_key},
                actor_id TEXT NOT NULL,
                action TEXT NOT NULL,
                target_user_id TEXT,
                summary TEXT NOT NULL,
                created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
            )
            """
        )
        conn.commit()
