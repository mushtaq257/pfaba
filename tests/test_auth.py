import base64
import time
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi import HTTPException
from jose import jwt
import requests

from backend.app.services.auth import get_auth_payload, get_auth_roles, verify_token


def _encode_integer(value):
    length = (value.bit_length() + 7) // 8
    encoded = value.to_bytes(length, "big")
    return base64.urlsafe_b64encode(encoded).rstrip(b"=").decode("ascii")


class Auth0TokenTests(unittest.TestCase):
    def setUp(self):
        self.domain = "finance-test.auth0.com"
        self.audience = "https://finance-api.example.com"
        self.private_key = rsa.generate_private_key(
            public_exponent=65537,
            key_size=2048,
        )
        public_numbers = self.private_key.public_key().public_numbers()
        self.jwks = {
            "keys": [{
                "kty": "RSA",
                "kid": "test-key",
                "use": "sig",
                "alg": "RS256",
                "n": _encode_integer(public_numbers.n),
                "e": _encode_integer(public_numbers.e),
            }],
        }

    def _token(self, audience=None):
        return jwt.encode(
            {
                "sub": "auth0|test-user",
                "aud": audience or self.audience,
                "iss": f"https://{self.domain}/",
                "exp": int(time.time()) + 60,
            },
            self.private_key,
            algorithm="RS256",
            headers={"kid": "test-key"},
        )

    def test_auth_roles_normalize_strings_and_ignore_non_string_values(self):
        self.assertEqual(get_auth_roles({"roles": "admin"}), ["admin"])
        self.assertEqual(get_auth_roles({"roles": ["admin", 3, None]}), ["admin"])
        self.assertEqual(get_auth_roles({"roles": 3}), [])

    @patch("backend.app.services.auth.get_settings")
    def test_requires_auth0_configuration_instead_of_disabling_auth(self, get_settings):
        get_settings.return_value = SimpleNamespace(auth0_enabled=False)
        request = Mock()
        request.headers = {}

        with self.assertRaises(HTTPException) as raised:
            get_auth_payload(request)

        self.assertEqual(raised.exception.status_code, 503)

    @patch("backend.app.services.auth.get_settings")
    def test_requires_bearer_token_when_auth0_is_configured(self, get_settings):
        get_settings.return_value = SimpleNamespace(auth0_enabled=True)
        request = Mock()
        request.headers = {}

        with self.assertRaises(HTTPException) as raised:
            get_auth_payload(request)

        self.assertEqual(raised.exception.status_code, 401)

    @patch("backend.app.services.auth.verify_token")
    @patch("backend.app.services.auth.get_settings")
    def test_auth_payload_rejects_malformed_bearer_headers(self, get_settings, verify):
        get_settings.return_value = SimpleNamespace(auth0_enabled=True)

        for authorization in ("Basic abc", "Bearer "):
            request = Mock()
            request.headers = {"Authorization": authorization}
            with self.subTest(authorization=authorization):
                with self.assertRaises(HTTPException) as raised:
                    get_auth_payload(request)
                self.assertEqual(raised.exception.status_code, 401)

        verify.assert_not_called()

    @patch("backend.app.services.auth.verify_token", return_value={"sub": "  "})
    @patch("backend.app.services.auth.get_settings")
    def test_auth_payload_rejects_missing_subject(self, get_settings, verify):
        get_settings.return_value = SimpleNamespace(auth0_enabled=True)
        request = Mock()
        request.headers = {"Authorization": "Bearer token"}

        with self.assertRaises(HTTPException) as raised:
            get_auth_payload(request)

        self.assertEqual(raised.exception.status_code, 401)

    @patch("backend.app.services.auth.verify_token", return_value={"sub": "auth0|alice", "name": "Alice"})
    @patch("backend.app.services.auth.get_settings")
    def test_auth_payload_returns_verified_user_claims(self, get_settings, verify):
        get_settings.return_value = SimpleNamespace(auth0_enabled=True)
        request = Mock()
        request.headers = {"Authorization": "Bearer signed-token"}

        self.assertEqual(
            get_auth_payload(request),
            {"sub": "auth0|alice", "name": "Alice"},
        )
        verify.assert_called_once_with("signed-token")

    @patch("backend.app.services.auth.get_settings")
    def test_verify_token_uses_development_mode_when_provider_is_unconfigured(self, get_settings):
        get_settings.return_value = SimpleNamespace(auth0_domain="", auth0_audience="")

        self.assertEqual(verify_token("anything"), {
            "status": "dev_mode",
            "message": "Authentication disabled in local environment.",
        })

    @patch("backend.app.services.auth.get_settings")
    def test_verify_token_rejects_malformed_token_header(self, get_settings):
        get_settings.return_value = SimpleNamespace(
            auth0_domain=self.domain,
            auth0_audience=self.audience,
        )

        with self.assertRaises(HTTPException) as raised:
            verify_token("not-a-jwt")

        self.assertEqual(raised.exception.status_code, 401)

    @patch("backend.app.services.auth.jwt.get_unverified_header", return_value={"alg": "HS256", "kid": "test-key"})
    @patch("backend.app.services.auth.get_settings")
    @patch("backend.app.services.auth.requests.get")
    def test_verify_token_rejects_unsupported_algorithm_before_fetching_keys(
        self, get, get_settings, get_header
    ):
        get_settings.return_value = SimpleNamespace(
            auth0_domain=self.domain,
            auth0_audience=self.audience,
        )

        with self.assertRaises(HTTPException) as raised:
            verify_token("token")

        self.assertEqual(raised.exception.status_code, 401)
        get.assert_not_called()

    @patch("backend.app.services.auth.get_settings")
    @patch("backend.app.services.auth.requests.get", side_effect=requests.RequestException("offline"))
    def test_verify_token_reports_auth_provider_network_failure(self, get, get_settings):
        get_settings.return_value = SimpleNamespace(
            auth0_domain=self.domain,
            auth0_audience=self.audience,
        )

        with self.assertRaises(HTTPException) as raised:
            verify_token(self._token())

        self.assertEqual(raised.exception.status_code, 503)

    @patch("backend.app.services.auth.get_settings")
    @patch("backend.app.services.auth.requests.get")
    def test_verify_token_rejects_invalid_jwks_json_and_shape(self, get, get_settings):
        get_settings.return_value = SimpleNamespace(
            auth0_domain=self.domain,
            auth0_audience=self.audience,
        )
        response = Mock()
        get.return_value = response

        response.json.side_effect = ValueError("invalid JSON")
        with self.assertRaises(HTTPException) as invalid_json:
            verify_token(self._token())
        self.assertEqual(invalid_json.exception.status_code, 502)

        response.json.side_effect = None
        response.json.return_value = {"keys": {}}
        with self.assertRaises(HTTPException) as invalid_shape:
            verify_token(self._token())
        self.assertEqual(invalid_shape.exception.status_code, 502)

    @patch("backend.app.services.auth.get_settings")
    @patch("backend.app.services.auth.requests.get")
    def test_verify_token_rejects_missing_or_ineligible_signing_key(self, get, get_settings):
        get_settings.return_value = SimpleNamespace(
            auth0_domain=self.domain,
            auth0_audience=self.audience,
        )
        response = Mock()
        response.json.return_value = {"keys": [
            {"kid": "test-key", "kty": "RSA", "alg": "HS256", "use": "sig"},
            None,
        ]}
        get.return_value = response

        with self.assertRaises(HTTPException) as raised:
            verify_token(self._token())

        self.assertEqual(raised.exception.status_code, 401)

    @patch("backend.app.services.auth.get_settings")
    @patch("backend.app.services.auth.requests.get")
    def test_verifies_rs256_token_using_matching_auth0_jwks(self, get, get_settings):
        get_settings.return_value = SimpleNamespace(
            auth0_domain=self.domain,
            auth0_audience=self.audience,
        )
        response = Mock()
        response.json.return_value = self.jwks
        get.return_value = response

        payload = verify_token(self._token())

        self.assertEqual(payload["sub"], "auth0|test-user")
        get.assert_called_once_with(
            f"https://{self.domain}/.well-known/jwks.json",
            timeout=5,
        )

    @patch("backend.app.services.auth.get_settings")
    @patch("backend.app.services.auth.requests.get")
    def test_normalizes_auth0_domains_with_http_or_https_prefix(self, get, get_settings):
        response = Mock()
        response.json.return_value = self.jwks
        get.return_value = response
        token = self._token()

        for configured_domain in (f"https://{self.domain}/", f"http://{self.domain}/"):
            with self.subTest(configured_domain=configured_domain):
                get_settings.return_value = SimpleNamespace(
                    auth0_domain=configured_domain,
                    auth0_audience=self.audience,
                )
                payload = verify_token(token)
                self.assertEqual(payload["sub"], "auth0|test-user")

        self.assertEqual(get.call_count, 2)

    @patch("backend.app.services.auth.get_settings")
    @patch("backend.app.services.auth.requests.get")
    def test_rejects_token_with_wrong_audience(self, get, get_settings):
        get_settings.return_value = SimpleNamespace(
            auth0_domain=self.domain,
            auth0_audience=self.audience,
        )
        response = Mock()
        response.json.return_value = self.jwks
        get.return_value = response

        with self.assertRaises(HTTPException) as raised:
            verify_token(self._token("https://wrong-audience.example.com"))

        self.assertEqual(raised.exception.status_code, 401)


if __name__ == "__main__":
    unittest.main()
