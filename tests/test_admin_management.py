import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

from fastapi import HTTPException
from fastapi.testclient import TestClient
import requests

from backend.app.main import app
from backend.app.services import auth0_management


class Auth0ManagementClientTests(unittest.TestCase):
    @patch("backend.app.services.auth0_management.get_settings")
    def test_management_domain_normalizes_http_scheme(self, get_settings):
        get_settings.return_value = SimpleNamespace(
            auth0_domain="http://finance-test.auth0.com/"
        )

        self.assertEqual(
            auth0_management._management_domain(),
            "finance-test.auth0.com",
        )

    @patch("backend.app.services.auth0_management.get_settings")
    def test_management_token_requires_management_api_configuration(self, get_settings):
        get_settings.return_value = SimpleNamespace(auth0_management_enabled=False)

        with self.assertRaises(HTTPException) as raised:
            auth0_management.get_management_token()

        self.assertEqual(raised.exception.status_code, 503)

    @patch("backend.app.services.auth0_management.get_settings")
    @patch(
        "backend.app.services.auth0_management.requests.post",
        side_effect=requests.RequestException("offline"),
    )
    def test_management_token_reports_network_and_invalid_response_errors(
        self, post, get_settings
    ):
        get_settings.return_value = SimpleNamespace(
            auth0_domain="finance-test.auth0.com",
            auth0_management_enabled=True,
            auth0_management_client_id="management-client",
            auth0_management_client_secret="management-secret",
        )

        with self.assertRaises(HTTPException) as raised:
            auth0_management.get_management_token()
        self.assertEqual(raised.exception.status_code, 503)

        post.side_effect = None
        post.return_value = Mock(ok=True, json=Mock(side_effect=ValueError("invalid JSON")))
        with self.assertRaises(HTTPException) as raised:
            auth0_management.get_management_token()
        self.assertEqual(raised.exception.status_code, 502)

        post.return_value = Mock(ok=True, json=Mock(return_value=[]))
        with self.assertRaises(HTTPException) as raised:
            auth0_management.get_management_token()
        self.assertEqual(raised.exception.status_code, 502)

    @patch("backend.app.services.auth0_management.get_settings")
    @patch("backend.app.services.auth0_management.requests.post")
    def test_management_token_classifies_scope_and_unrecognized_errors(
        self, post, get_settings
    ):
        get_settings.return_value = SimpleNamespace(
            auth0_domain="finance-test.auth0.com",
            auth0_management_enabled=True,
            auth0_management_client_id="management-client",
            auth0_management_client_secret="management-secret",
        )
        post.return_value = Mock(
            ok=False,
            json=Mock(return_value={"error": "invalid_scope"}),
        )
        with self.assertRaises(HTTPException) as raised:
            auth0_management.get_management_token()
        self.assertIn("scopes", raised.exception.detail)

        post.return_value = Mock(ok=False, json=Mock(side_effect=ValueError("invalid JSON")))
        with self.assertRaises(HTTPException) as raised:
            auth0_management.get_management_token()
        self.assertIn("rejected the Management API token request", raised.exception.detail)

    @patch("backend.app.services.auth0_management.get_settings")
    @patch("backend.app.services.auth0_management.requests.post")
    def test_management_token_uses_dedicated_m2m_credentials_and_scopes(
        self, post, get_settings
    ):
        get_settings.return_value = SimpleNamespace(
            auth0_domain="https://finance-test.auth0.com/",
            auth0_management_enabled=True,
            auth0_management_client_id="management-client",
            auth0_management_client_secret="management-secret",
        )
        post.return_value = Mock(
            ok=True,
            json=Mock(return_value={"access_token": "management-token"}),
        )

        token = auth0_management.get_management_token()

        self.assertEqual(token, "management-token")
        post.assert_called_once_with(
            "https://finance-test.auth0.com/oauth/token",
            json={
                "grant_type": "client_credentials",
                "client_id": "management-client",
                "client_secret": "management-secret",
                "audience": "https://finance-test.auth0.com/api/v2/",
                "scope": "read:users update:users create:users delete:users",
            },
            timeout=auth0_management.MANAGEMENT_TIMEOUT_SECONDS,
        )

    @patch("backend.app.services.auth0_management.get_settings")
    @patch("backend.app.services.auth0_management.requests.post")
    def test_management_token_reports_missing_api_authorization(
        self, post, get_settings
    ):
        get_settings.return_value = SimpleNamespace(
            auth0_domain="finance-test.auth0.com",
            auth0_management_enabled=True,
            auth0_management_client_id="management-client",
            auth0_management_client_secret="management-secret",
        )
        post.return_value = Mock(
            ok=False,
            json=Mock(return_value={"error": "access_denied"}),
        )

        with self.assertRaises(HTTPException) as raised:
            auth0_management.get_management_token()

        self.assertIn("not authorized", raised.exception.detail)
        self.assertIn("read:users", raised.exception.detail)

    @patch("backend.app.services.auth0_management.get_settings")
    @patch("backend.app.services.auth0_management.requests.post")
    def test_management_token_reports_invalid_client_credentials(
        self, post, get_settings
    ):
        get_settings.return_value = SimpleNamespace(
            auth0_domain="finance-test.auth0.com",
            auth0_management_enabled=True,
            auth0_management_client_id="management-client",
            auth0_management_client_secret="management-secret",
        )
        post.return_value = Mock(
            ok=False,
            json=Mock(return_value={"error": "invalid_client"}),
        )

        with self.assertRaises(HTTPException) as raised:
            auth0_management.get_management_token()

        self.assertIn("same Auth0 tenant", raised.exception.detail)

    @patch(
        "backend.app.services.auth0_management._management_domain",
        return_value="finance-test.auth0.com",
    )
    @patch("backend.app.services.auth0_management.requests.request")
    def test_bad_password_response_is_classified_without_returning_auth0_message(
        self, request, management_domain
    ):
        request.return_value = Mock(
            ok=False,
            status_code=400,
            json=Mock(return_value={"message": "Password is not strong enough"}),
        )

        with self.assertRaises(HTTPException) as raised:
            auth0_management._management_request(
                "token",
                "POST",
                "/api/v2/users",
                body={"password": "do-not-echo-this"},
            )

        self.assertIn("password policy", raised.exception.detail)
        self.assertNotIn("do-not-echo-this", raised.exception.detail)

    @patch(
        "backend.app.services.auth0_management._management_domain",
        return_value="finance-test.auth0.com",
    )
    @patch("backend.app.services.auth0_management.requests.request")
    def test_management_request_maps_http_errors(self, request, management_domain):
        cases = [
            (404, 404, "not found"),
            (403, 502, "lacks the required scopes"),
            (409, 409, "already exists"),
            (500, 502, "request failed"),
        ]
        for response_status, expected_status, expected_detail in cases:
            request.return_value = Mock(ok=False, status_code=response_status)
            with self.subTest(response_status=response_status):
                with self.assertRaises(HTTPException) as raised:
                    auth0_management._management_request("token", "GET", "/api/v2/users")
                self.assertEqual(raised.exception.status_code, expected_status)
                self.assertIn(expected_detail, raised.exception.detail)

    @patch(
        "backend.app.services.auth0_management._management_domain",
        return_value="finance-test.auth0.com",
    )
    @patch("backend.app.services.auth0_management.requests.request")
    def test_management_request_reports_network_errors_and_204_response(
        self, request, management_domain
    ):
        request.side_effect = requests.RequestException("offline")
        with self.assertRaises(HTTPException) as raised:
            auth0_management._management_request("token", "GET", "/api/v2/users")
        self.assertEqual(raised.exception.status_code, 503)

        request.side_effect = None
        request.return_value = Mock(ok=True, status_code=204)
        self.assertIsNone(
            auth0_management._management_request("token", "DELETE", "/api/v2/users/1")
        )

    @patch(
        "backend.app.services.auth0_management._management_domain",
        return_value="finance-test.auth0.com",
    )
    @patch("backend.app.services.auth0_management.requests.request")
    def test_management_request_classifies_bad_request_payloads(
        self, request, management_domain
    ):
        cases = [
            ("POST", "/api/v2/users", None, {"message": "invalid username"}, "username"),
            ("PATCH", "/api/v2/users/1", None, {"message": "invalid connection"}, "database connection"),
            ("POST", "/api/v2/users", None, {"message": "invalid fields"}, "rejected user creation"),
            ("PATCH", "/api/v2/users/1", {"password": "secret"}, {"message": "invalid"}, "password update"),
            ("PATCH", "/api/v2/users/1", None, {"message": "invalid"}, "requested user update"),
            ("POST", "/api/v2/users", None, [], "rejected user creation"),
        ]
        for method, path, body, payload, expected_detail in cases:
            request.return_value = Mock(
                ok=False,
                status_code=400,
                json=Mock(return_value=payload),
            )
            with self.subTest(method=method, path=path, body=body):
                with self.assertRaises(HTTPException) as raised:
                    auth0_management._management_request(
                        "token", method, path, body=body
                    )
                self.assertEqual(raised.exception.status_code, 422)
                self.assertIn(expected_detail, raised.exception.detail)

        request.return_value = Mock(
            ok=False,
            status_code=400,
            json=Mock(side_effect=ValueError("invalid JSON")),
        )
        with self.assertRaises(HTTPException) as raised:
            auth0_management._management_request("token", "POST", "/api/v2/users")
        self.assertIn("rejected user creation", raised.exception.detail)

    @patch(
        "backend.app.services.auth0_management._management_domain",
        return_value="finance-test.auth0.com",
    )
    @patch("backend.app.services.auth0_management.requests.request")
    def test_management_request_rejects_invalid_success_json(self, request, management_domain):
        request.return_value = Mock(
            ok=True,
            status_code=200,
            json=Mock(side_effect=ValueError("invalid JSON")),
        )

        with self.assertRaises(HTTPException) as raised:
            auth0_management._management_request("token", "GET", "/api/v2/users")

        self.assertEqual(raised.exception.status_code, 502)

    @patch("backend.app.services.auth0_management._management_request")
    @patch("backend.app.services.auth0_management.get_management_token", return_value="token")
    def test_user_listing_rejects_invalid_provider_data(self, get_token, request):
        for invalid_result in ({"users": []}, [None], [{"email": "missing-id@example.com"}]):
            request.return_value = invalid_result
            with self.subTest(invalid_result=invalid_result):
                with self.assertRaises(HTTPException) as raised:
                    auth0_management.list_management_users()
                self.assertEqual(raised.exception.status_code, 502)

    @patch("backend.app.services.auth0_management._management_request")
    @patch("backend.app.services.auth0_management.get_management_token", return_value="token")
    def test_user_listing_maps_status_and_account_details(self, get_token, request):
        request.return_value = [{
            "user_id": "auth0|alice",
            "name": "Alice Example",
            "username": "alice",
            "email": "alice@example.com",
            "email_verified": True,
            "blocked": False,
            "created_at": "2026-01-01T00:00:00Z",
            "last_login": "2026-02-01T00:00:00Z",
            "logins_count": 4,
            "identities": [{"provider": "auth0", "connection": "FinanceUsers"}],
        }]

        users = auth0_management.list_management_users()

        self.assertEqual(users[0]["status"], "Active")
        self.assertEqual(users[0]["user_id"], "auth0|alice")
        self.assertEqual(users[0]["connections"], ["FinanceUsers"])
        self.assertEqual(users[0]["database_connections"], ["FinanceUsers"])

    @patch("backend.app.services.auth0_management._management_request")
    @patch("backend.app.services.auth0_management.get_management_token", return_value="token")
    def test_create_user_sends_database_fields_and_never_returns_password(self, get_token, request):
        request.return_value = {
            "user_id": "auth0|new-user",
            "name": "New User",
            "email": "new@example.com",
            "username": "new-user",
            "identities": [{"provider": "auth0", "connection": "FinanceUsers"}],
        }

        user = auth0_management.create_management_user(
            " New User ",
            " new@example.com ",
            " new-user ",
            "private-password",
            " FinanceUsers ",
        )

        self.assertEqual(user["user_id"], "auth0|new-user")
        self.assertNotIn("password", user)
        request.assert_called_once_with(
            "token",
            "POST",
            "/api/v2/users",
            body={
                "name": "New User",
                "email": "new@example.com",
                "username": "new-user",
                "password": "private-password",
                "connection": "FinanceUsers",
            },
        )

    @patch("backend.app.services.auth0_management.get_management_token")
    def test_create_user_validates_required_fields_and_nonblank_username(self, get_token):
        with self.assertRaises(HTTPException) as missing_fields:
            auth0_management.create_management_user("", "alice@example.com", None, "password", "Users")
        self.assertEqual(missing_fields.exception.status_code, 422)

        with self.assertRaises(HTTPException) as blank_username:
            auth0_management.create_management_user("Alice", "alice@example.com", "  ", "password", "Users")
        self.assertEqual(blank_username.exception.status_code, 422)
        get_token.assert_not_called()

    @patch("backend.app.services.auth0_management._management_request", return_value=[])
    @patch("backend.app.services.auth0_management.get_management_token", return_value="token")
    def test_create_user_rejects_invalid_provider_response(self, get_token, request):
        with self.assertRaises(HTTPException) as raised:
            auth0_management.create_management_user(
                "Alice", "alice@example.com", None, "password", "Users"
            )
        self.assertEqual(raised.exception.status_code, 502)

    @patch("backend.app.services.auth0_management._management_request", return_value=None)
    @patch("backend.app.services.auth0_management.get_management_token", return_value="token")
    def test_delete_user_uses_management_api(self, get_token, request):
        result = auth0_management.delete_management_user("auth0|alice")

        self.assertEqual(result, {"user_id": "auth0|alice", "deleted": True})
        request.assert_called_once_with("token", "DELETE", "/api/v2/users/auth0%7Calice")

    @patch("backend.app.services.auth0_management._management_request")
    @patch("backend.app.services.auth0_management.get_management_token", return_value="token")
    def test_user_listing_fetches_all_pages(self, get_token, request):
        first_page = [{"user_id": f"auth0|user-{index}"} for index in range(100)]
        request.side_effect = [first_page, [{"user_id": "auth0|last-user"}]]

        users = auth0_management.list_management_users()

        self.assertEqual(len(users), 101)
        self.assertEqual(request.call_args_list[0].kwargs["params"]["page"], 0)
        self.assertEqual(request.call_args_list[1].kwargs["params"]["page"], 1)

    @patch("backend.app.services.auth0_management._management_request")
    @patch("backend.app.services.auth0_management.get_management_token", return_value="token")
    def test_status_changes_and_password_updates_target_auth0_database_users(
        self, get_token, request
    ):
        request.return_value = {"blocked": True}
        status = auth0_management.set_user_enabled("auth0|alice", False)
        self.assertFalse(status["enabled"])

        request.side_effect = [
            {"identities": [{
                "provider": "auth0",
                "connection": "FinanceUsers",
            }]},
            {},
        ]
        password = auth0_management.set_user_password("auth0|alice", "long-password")

        self.assertTrue(password["updated"])
        self.assertEqual(request.call_args.args[2], "/api/v2/users/auth0%7Calice")
        self.assertEqual(
            request.call_args.kwargs["body"],
            {"password": "long-password", "connection": "FinanceUsers"},
        )

    @patch("backend.app.services.auth0_management._management_request", return_value={})
    @patch("backend.app.services.auth0_management.get_management_token", return_value="token")
    def test_status_update_rejects_invalid_provider_response(self, get_token, request):
        with self.assertRaises(HTTPException) as raised:
            auth0_management.set_user_enabled("auth0|alice", True)
        self.assertEqual(raised.exception.status_code, 502)

    @patch("backend.app.services.auth0_management._management_request", return_value={})
    @patch("backend.app.services.auth0_management.get_management_token", return_value="token")
    def test_password_update_rejects_invalid_identity_data(self, get_token, request):
        with self.assertRaises(HTTPException) as raised:
            auth0_management.set_user_password("auth0|alice", "long-password")
        self.assertEqual(raised.exception.status_code, 502)

    @patch("backend.app.services.auth0_management._management_request")
    @patch("backend.app.services.auth0_management.get_management_token", return_value="token")
    def test_password_change_rejects_non_database_identities(self, get_token, request):
        request.return_value = {
            "identities": [{"provider": "google-oauth2", "connection": "Google"}],
        }

        with self.assertRaises(HTTPException) as raised:
            auth0_management.set_user_password("google-oauth2|alice", "long-password")

        self.assertEqual(raised.exception.status_code, 409)


class AdminApiTests(unittest.TestCase):
    @patch("backend.app.main.list_management_users")
    @patch(
        "backend.app.services.auth.get_auth_payload",
        return_value={"sub": "auth0|alice", "roles": ["user"]},
    )
    def test_user_list_rejects_non_admin_before_management_api_call(
        self, get_auth_payload, list_users
    ):
        response = TestClient(app).get("/api/admin/users")

        self.assertEqual(response.status_code, 403)
        list_users.assert_not_called()

    @patch("backend.app.main.list_management_users", return_value=[])
    @patch(
        "backend.app.services.auth.get_auth_payload",
        return_value={
            "sub": "auth0|admin",
            "https://finance.example/roles": ["admin"],
        },
    )
    def test_namespaced_admin_role_can_access_admin_api(self, get_auth_payload, list_users):
        response = TestClient(app).get("/api/admin/users")

        self.assertEqual(response.status_code, 200)
        list_users.assert_called_once_with()

    @patch("backend.app.main.list_management_users")
    @patch(
        "backend.app.services.auth.get_auth_payload",
        return_value={"sub": "auth0|alice", "roles": ["user"]},
    )
    def test_non_admin_cannot_call_admin_mutations(self, get_auth_payload, list_users):
        client = TestClient(app)
        requests = [
            (
                "/api/admin/users/auth0%7Calice/status",
                {"enabled": False},
            ),
            (
                "/api/admin/users/auth0%7Calice/password",
                {"password": "safe-password-123"},
            ),
            (
                "/api/admin/users/auth0%7Calice/historical-permissions",
                {
                    "can_edit_previous_month": True,
                    "can_delete_previous_month": True,
                    "can_clear_previous_month": True,
                },
            ),
            (
                "/api/admin/users/auth0%7Calice",
                None,
            ),
        ]

        responses = [client.patch(path, json=body) for path, body in requests[:3]]
        responses.append(client.delete(requests[3][0]))
        responses.append(client.post(
            "/api/admin/users",
            json={
                "name": "New user",
                "email": "new@example.com",
                "password": "password-123",
                "connection": "FinanceUsers",
            },
        ))
        responses.append(client.get("/api/admin/audit-log"))

        self.assertEqual(
            [response.status_code for response in responses],
            [403, 403, 403, 403, 403, 403],
        )
        list_users.assert_not_called()

    @patch("backend.app.main.record_admin_audit_log")
    @patch("backend.app.main.create_management_user")
    @patch("backend.app.main.require_admin", return_value={"sub": "auth0|admin"})
    def test_admin_can_create_user(self, require_admin, create_user, record_log):
        create_user.return_value = {
            "user_id": "auth0|new",
            "status": "Active",
        }

        response = TestClient(app).post(
            "/api/admin/users",
            json={
                "name": "New user",
                "email": "new@example.com",
                "password": "password-123",
                "connection": "FinanceUsers",
            },
        )

        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.json()["data"]["user"]["user_id"], "auth0|new")
        self.assertEqual(
            response.json()["data"]["user"]["historical_permissions"],
            {
                "can_edit_previous_month": False,
                "can_delete_previous_month": False,
                "can_clear_previous_month": False,
            },
        )
        self.assertEqual(record_log.call_args.args[1], "user.created")

    @patch("backend.app.main.record_admin_audit_log")
    @patch("backend.app.main.delete_management_user")
    @patch("backend.app.main.require_admin", return_value={"sub": "auth0|admin"})
    def test_admin_can_delete_another_user(self, require_admin, delete_user, record_log):
        delete_user.return_value = {"user_id": "auth0|alice", "deleted": True}

        response = TestClient(app).delete("/api/admin/users/auth0%7Calice")

        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json()["data"]["deleted"])
        record_log.assert_called_once_with(
            "auth0|admin",
            "user.deleted",
            "auth0|alice",
            "Deleted user account",
        )

    @patch("backend.app.main.record_admin_audit_log")
    @patch("backend.app.main.set_user_password", return_value={"user_id": "auth0|alice", "updated": True})
    @patch("backend.app.main.require_admin", return_value={"sub": "auth0|admin"})
    def test_admin_can_update_another_users_password(
        self, require_admin, set_password, record_log
    ):
        response = TestClient(app).patch(
            "/api/admin/users/auth0%7Calice/password",
            json={"password": "new-password-123"},
        )

        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json()["data"]["updated"])
        set_password.assert_called_once_with("auth0|alice", "new-password-123")
        record_log.assert_called_once_with(
            "auth0|admin",
            "user.password_updated",
            "auth0|alice",
            "Updated user password",
        )

    @patch("backend.app.main.record_admin_audit_log")
    @patch("backend.app.main.set_user_enabled")
    @patch("backend.app.main.require_admin", return_value={"sub": "auth0|admin"})
    def test_admin_can_enable_or_disable_another_user(
        self, require_admin, set_enabled, record_log
    ):
        client = TestClient(app)
        set_enabled.side_effect = [
            {"user_id": "auth0|alice", "enabled": True},
            {"user_id": "auth0|alice", "enabled": False},
        ]

        enabled = client.patch(
            "/api/admin/users/auth0%7Calice/status",
            json={"enabled": True},
        )
        disabled = client.patch(
            "/api/admin/users/auth0%7Calice/status",
            json={"enabled": False},
        )

        self.assertEqual(enabled.status_code, 200)
        self.assertTrue(enabled.json()["data"]["enabled"])
        self.assertEqual(disabled.status_code, 200)
        self.assertFalse(disabled.json()["data"]["enabled"])
        self.assertEqual(
            [call.args[1] for call in record_log.call_args_list],
            ["user.enabled", "user.disabled"],
        )

    @patch("backend.app.main.set_historical_permissions")
    @patch("backend.app.main.set_user_enabled")
    @patch("backend.app.main.delete_management_user")
    @patch("backend.app.main.require_admin", return_value={"sub": "auth0|admin"})
    def test_admin_cannot_disable_delete_or_set_finance_permissions_for_self(
        self, require_admin, delete_user, set_user_enabled, set_permissions
    ):
        client = TestClient(app)
        disable_response = client.patch(
            "/api/admin/users/auth0%7Cadmin/status",
            json={"enabled": False},
        )
        delete_response = client.delete("/api/admin/users/auth0%7Cadmin")
        permission_response = client.patch(
            "/api/admin/users/auth0%7Cadmin/historical-permissions",
            json={
                "can_edit_previous_month": True,
                "can_delete_previous_month": True,
                "can_clear_previous_month": True,
            },
        )

        self.assertEqual(disable_response.status_code, 409)
        self.assertEqual(delete_response.status_code, 409)
        self.assertEqual(permission_response.status_code, 409)
        delete_user.assert_not_called()
        set_user_enabled.assert_not_called()
        set_permissions.assert_not_called()

    @patch("backend.app.main.list_admin_audit_log")
    @patch("backend.app.main.require_admin", return_value={"sub": "auth0|admin"})
    def test_admin_can_read_application_audit_log(self, require_admin, audit_log):
        audit_log.return_value = [{
            "action": "user.created",
            "summary": "Created user account",
        }]

        response = TestClient(app).get("/api/admin/audit-log")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.json()["data"]["logs"][0]["action"],
            "user.created",
        )

    @patch("backend.app.main.get_historical_permissions_for_users")
    @patch("backend.app.main.list_management_users")
    @patch("backend.app.main.require_admin", return_value={"sub": "auth0|admin"})
    def test_admin_user_list_combines_auth0_accounts_and_app_permissions(
        self, require_admin, list_users, permissions
    ):
        list_users.return_value = [{
            "user_id": "auth0|alice",
            "status": "Active",
        }]
        permissions.return_value = {
            "auth0|alice": {
                "can_edit_previous_month": True,
                "can_delete_previous_month": False,
                "can_clear_previous_month": False,
            },
        }

        response = TestClient(app).get("/api/admin/users")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.json()["data"]["users"][0]["historical_permissions"]["can_edit_previous_month"],
            True,
        )
        permissions.assert_called_once_with(["auth0|alice"])

    @patch("backend.app.main.set_historical_permissions")
    @patch("backend.app.main.require_admin", return_value={"sub": "auth0|admin"})
    def test_admin_can_update_individual_historical_permissions(
        self, require_admin, set_permissions
    ):
        set_permissions.return_value = {
            "can_edit_previous_month": True,
            "can_delete_previous_month": False,
            "can_clear_previous_month": True,
        }

        response = TestClient(app).patch(
            "/api/admin/users/auth0%7Calice/historical-permissions",
            json={
                "can_edit_previous_month": True,
                "can_delete_previous_month": False,
                "can_clear_previous_month": True,
            },
        )

        self.assertEqual(response.status_code, 200)
        set_permissions.assert_called_once_with(
            "auth0|alice",
            {
                "can_edit_previous_month": True,
                "can_delete_previous_month": False,
                "can_clear_previous_month": True,
            },
            "auth0|admin",
        )


if __name__ == "__main__":
    unittest.main()
