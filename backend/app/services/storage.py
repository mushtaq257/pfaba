from __future__ import annotations

from contextlib import closing
from typing import Any, Dict, List, Optional

from backend.app.database import get_connection

DEFAULT_HISTORICAL_PERMISSIONS = {
    "can_edit_previous_month": False,
    "can_delete_previous_month": False,
    "can_clear_previous_month": False,
}


def upsert_profile(session_id: str, income: float, currency: str, location: Optional[str]) -> None:
    with closing(get_connection()) as conn:
        conn.execute(
            """
            INSERT INTO profiles (session_id, income, currency, location, updated_at)
            VALUES (?, ?, ?, ?, CURRENT_TIMESTAMP)
            ON CONFLICT(session_id)
            DO UPDATE SET income = excluded.income, currency = excluded.currency, location = excluded.location, updated_at = CURRENT_TIMESTAMP
            """,
            (session_id, income, currency, location),
        )
        conn.commit()


def save_transactions(session_id: str, transactions: List[Dict[str, Any]]) -> None:
    with closing(get_connection()) as conn:
        conn.execute("DELETE FROM transactions WHERE session_id = ?", (session_id,))
        for item in transactions:
            conn.execute(
                """
                INSERT INTO transactions (session_id, description, amount, currency, category)
                VALUES (?, ?, ?, ?, ?)
                """,
                (
                    session_id,
                    item.get("description"),
                    float(item.get("amount", 0) or 0),
                    item.get("currency", "USD"),
                    item.get("category"),
                ),
            )
        conn.commit()


def save_goals(session_id: str, goals: List[Dict[str, Any]]) -> None:
    with closing(get_connection()) as conn:
        conn.execute("DELETE FROM goals WHERE session_id = ?", (session_id,))
        for entry in goals:
            conn.execute(
                """
                INSERT INTO goals (session_id, name, target_amount, saved_amount)
                VALUES (?, ?, ?, ?)
                """,
                (
                    session_id,
                    entry.get("name"),
                    float(entry.get("target_amount") or entry.get("target") or 0),
                    float(entry.get("saved_amount") or entry.get("saved") or 0),
                ),
            )
        conn.commit()


def load_session(session_id: str) -> Dict[str, Any]:
    with closing(get_connection()) as conn:
        profile = conn.execute(
            "SELECT session_id, income, currency, location FROM profiles WHERE session_id = ?",
            (session_id,),
        ).fetchone()
        transactions = conn.execute(
            "SELECT description, amount, currency, category FROM transactions WHERE session_id = ? ORDER BY id DESC",
            (session_id,),
        ).fetchall()
        goals = conn.execute(
            "SELECT name, target_amount AS target, saved_amount AS saved FROM goals WHERE session_id = ? ORDER BY id DESC",
            (session_id,),
        ).fetchall()

    return {
        "income": float(profile["income"]) if profile else 0.0,
        "currency": (profile["currency"] if profile else "USD") or "USD",
        "location": profile["location"] if profile else None,
        "transactions": [
            {
                "description": item["description"],
                "amount": float(item["amount"]),
                "currency": item["currency"],
                "category": item["category"],
            }
            for item in transactions
        ],
        "goals": [
            {
                "name": item["name"],
                "target": float(item["target"]),
                "saved": float(item["saved"]),
            }
            for item in goals
        ],
    }


def get_historical_permissions(session_id: str) -> Dict[str, bool]:
    with closing(get_connection()) as conn:
        row = conn.execute(
            """
            SELECT can_edit_previous_month, can_delete_previous_month, can_clear_previous_month
            FROM historical_permissions WHERE session_id = ?
            """,
            (session_id,),
        ).fetchone()
    if not row:
        return dict(DEFAULT_HISTORICAL_PERMISSIONS)
    return {
        "can_edit_previous_month": bool(row["can_edit_previous_month"]),
        "can_delete_previous_month": bool(row["can_delete_previous_month"]),
        "can_clear_previous_month": bool(row["can_clear_previous_month"]),
    }


def get_historical_permissions_for_users(session_ids: List[str]) -> Dict[str, Dict[str, bool]]:
    if not session_ids:
        return {}
    placeholders = ", ".join("?" for _ in session_ids)
    with closing(get_connection()) as conn:
        rows = conn.execute(
            f"""
            SELECT session_id, can_edit_previous_month, can_delete_previous_month, can_clear_previous_month
            FROM historical_permissions WHERE session_id IN ({placeholders})
            """,
            session_ids,
        ).fetchall()
    permissions = {
        row["session_id"]: {
            "can_edit_previous_month": bool(row["can_edit_previous_month"]),
            "can_delete_previous_month": bool(row["can_delete_previous_month"]),
            "can_clear_previous_month": bool(row["can_clear_previous_month"]),
        }
        for row in rows
    }
    return {
        session_id: permissions.get(session_id, dict(DEFAULT_HISTORICAL_PERMISSIONS))
        for session_id in session_ids
    }


def set_historical_permissions(
    session_id: str,
    permissions: Dict[str, bool],
    updated_by: str,
) -> Dict[str, bool]:
    normalized = {
        key: bool(permissions[key])
        for key in DEFAULT_HISTORICAL_PERMISSIONS
    }
    with closing(get_connection()) as conn:
        conn.execute(
            """
            INSERT INTO historical_permissions (
                session_id,
                can_edit_previous_month,
                can_delete_previous_month,
                can_clear_previous_month,
                updated_by,
                updated_at
            )
            VALUES (?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
            ON CONFLICT(session_id)
            DO UPDATE SET
                can_edit_previous_month = excluded.can_edit_previous_month,
                can_delete_previous_month = excluded.can_delete_previous_month,
                can_clear_previous_month = excluded.can_clear_previous_month,
                updated_by = excluded.updated_by,
                updated_at = CURRENT_TIMESTAMP
            """,
            (
                session_id,
                int(normalized["can_edit_previous_month"]),
                int(normalized["can_delete_previous_month"]),
                int(normalized["can_clear_previous_month"]),
                updated_by,
            ),
        )
        conn.commit()
    return normalized


def record_admin_audit_log(
    actor_id: str,
    action: str,
    target_user_id: Optional[str],
    summary: str,
) -> None:
    with closing(get_connection()) as conn:
        conn.execute(
            """
            INSERT INTO admin_audit_log (actor_id, action, target_user_id, summary)
            VALUES (?, ?, ?, ?)
            """,
            (actor_id, action, target_user_id, summary),
        )
        conn.commit()


def list_admin_audit_log(limit: int = 100) -> List[Dict[str, Any]]:
    bounded_limit = max(1, min(limit, 100))
    with closing(get_connection()) as conn:
        rows = conn.execute(
            """
            SELECT id, actor_id, action, target_user_id, summary, created_at
            FROM admin_audit_log
            ORDER BY id DESC
            LIMIT ?
            """,
            (bounded_limit,),
        ).fetchall()
    return [dict(row) for row in rows]
