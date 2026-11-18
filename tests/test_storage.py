import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from backend.app.database import init_db
from backend.app.services.storage import (
    get_historical_permissions,
    get_historical_permissions_for_users,
    list_admin_audit_log,
    load_session,
    record_admin_audit_log,
    save_goals,
    save_transactions,
    set_historical_permissions,
    upsert_profile,
)


class FinanceStorageTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.database_path = Path(self.temp_dir.name) / "finance.sqlite"
        self.database_path_patch = patch("backend.app.database.DB_PATH", self.database_path)
        self.database_path_patch.start()
        init_db()

    def tearDown(self):
        self.database_path_patch.stop()
        self.temp_dir.cleanup()

    def test_upserts_profile_and_replaces_transactions_and_goals(self):
        upsert_profile("auth0|alice", 50000, "INR", "Ahmedabad")
        upsert_profile("auth0|alice", 60000, "INR", "Pune")
        save_transactions("auth0|alice", [
            {"description": "Groceries", "amount": 450, "currency": "INR", "category": "Food"},
            {"description": "Miscellaneous"},
        ])
        save_goals("auth0|alice", [
            {"name": "Emergency", "target_amount": 5000, "saved_amount": 1200},
            {"name": "Travel", "target": 3000, "saved": 750},
        ])

        session = load_session("auth0|alice")

        self.assertEqual(session["income"], 60000)
        self.assertEqual(session["currency"], "INR")
        self.assertEqual(session["location"], "Pune")
        self.assertEqual(session["transactions"][0]["description"], "Miscellaneous")
        self.assertEqual(session["transactions"][0]["amount"], 0)
        self.assertEqual(session["transactions"][0]["currency"], "USD")
        self.assertEqual({goal["name"] for goal in session["goals"]}, {"Emergency", "Travel"})
        self.assertEqual(
            {goal["name"]: goal["target"] for goal in session["goals"]},
            {"Emergency": 5000, "Travel": 3000},
        )

        save_transactions("auth0|alice", [])
        save_goals("auth0|alice", [])
        cleared_session = load_session("auth0|alice")
        self.assertEqual(cleared_session["transactions"], [])
        self.assertEqual(cleared_session["goals"], [])

    def test_missing_session_returns_empty_financial_defaults(self):
        self.assertEqual(
            load_session("auth0|missing"),
            {
                "income": 0.0,
                "currency": "USD",
                "location": None,
                "transactions": [],
                "goals": [],
            },
        )

    def test_historical_permissions_default_to_denied_and_can_be_set_per_user(self):
        self.assertEqual(
            get_historical_permissions("auth0|alice"),
            {
                "can_edit_previous_month": False,
                "can_delete_previous_month": False,
                "can_clear_previous_month": False,
            },
        )

        updated = set_historical_permissions(
            "auth0|alice",
            {
                "can_edit_previous_month": True,
                "can_delete_previous_month": False,
                "can_clear_previous_month": True,
            },
            "auth0|admin",
        )

        self.assertEqual(updated["can_edit_previous_month"], True)
        self.assertEqual(
            get_historical_permissions("auth0|alice"),
            {
                "can_edit_previous_month": True,
                "can_delete_previous_month": False,
                "can_clear_previous_month": True,
            },
        )
        self.assertEqual(get_historical_permissions_for_users(["auth0|alice"]), {
            "auth0|alice": {
                "can_edit_previous_month": True,
                "can_delete_previous_month": False,
                "can_clear_previous_month": True,
            },
        })

    def test_admin_audit_log_records_actions_without_other_payload_data(self):
        record_admin_audit_log(
            "auth0|admin",
            "user.created",
            "auth0|alice",
            "Created user account",
        )

        logs = list_admin_audit_log()

        self.assertEqual(len(logs), 1)
        self.assertEqual(logs[0]["actor_id"], "auth0|admin")
        self.assertEqual(logs[0]["target_user_id"], "auth0|alice")
        self.assertEqual(logs[0]["summary"], "Created user account")


if __name__ == "__main__":
    unittest.main()
