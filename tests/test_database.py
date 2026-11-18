import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

from backend.app import database


class DatabaseConnectionTests(unittest.TestCase):
    @patch("backend.app.database.psycopg.connect")
    @patch(
        "backend.app.database.get_settings",
        return_value=SimpleNamespace(
            database_url="postgresql://user:secret@db.example/finance"
        ),
    )
    def test_postgres_connection_uses_dict_rows_and_translates_placeholders(
        self, get_settings, connect
    ):
        raw_connection = Mock()
        connect.return_value = raw_connection

        connection = database.get_connection()
        connection.execute("SELECT * FROM profiles WHERE session_id = ?", ("alice",))
        connection.commit()
        connection.close()

        connect.assert_called_once_with(
            "postgresql://user:secret@db.example/finance",
            row_factory=database.dict_row,
        )
        raw_connection.execute.assert_called_once_with(
            "SELECT * FROM profiles WHERE session_id = %s",
            ("alice",),
        )
        raw_connection.commit.assert_called_once_with()
        raw_connection.close.assert_called_once_with()

    @patch("backend.app.database.psycopg.connect")
    @patch(
        "backend.app.database.get_settings",
        return_value=SimpleNamespace(
            database_url="postgres://user:secret@db.example/finance"
        ),
    )
    def test_postgres_url_alias_is_normalized(self, get_settings, connect):
        connect.return_value = Mock()

        database.get_connection()

        connect.assert_called_once_with(
            "postgresql://user:secret@db.example/finance",
            row_factory=database.dict_row,
        )

    @patch(
        "backend.app.database.get_settings",
        return_value=SimpleNamespace(database_url="mysql://db.example/finance"),
    )
    def test_rejects_non_postgresql_database_urls(self, get_settings):
        with self.assertRaisesRegex(ValueError, "PostgreSQL URL scheme"):
            database.get_connection()

    @patch("backend.app.database.get_connection")
    @patch(
        "backend.app.database.get_settings",
        return_value=SimpleNamespace(
            database_url="postgresql://user:secret@db.example/finance"
        ),
    )
    def test_postgres_schema_uses_serial_primary_keys(self, get_settings, get_connection):
        connection = Mock()
        get_connection.return_value = connection

        database.init_db()

        schema_statements = [call.args[0] for call in connection.execute.call_args_list]
        self.assertEqual(len(schema_statements), 5)
        serial_primary_keys = [
            sql
            for sql in schema_statements
            if "BIGSERIAL PRIMARY KEY" in sql
        ]
        self.assertEqual(len(serial_primary_keys), 4)
        self.assertTrue(
            all("DOUBLE PRECISION" in sql for sql in schema_statements[:3])
        )
        connection.commit.assert_called_once_with()
        connection.close.assert_called_once_with()
