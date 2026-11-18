import unittest
from unittest.mock import Mock, patch

from fastapi.testclient import TestClient
import requests

from backend.app.main import app
from backend.app.services.api_clients import (
    convert_currency,
    fetch_exchange_rates,
    fetch_geolocation_context,
    reverse_geocode_coordinates,
)


class ExchangeRateApiTests(unittest.TestCase):
    @patch("backend.app.main.get_settings")
    def test_health_and_public_auth_configuration_routes(self, get_settings):
        get_settings.return_value = Mock(
            app_name="Finance Advisor",
            auth0_enabled=True,
            auth0_domain="finance-test.auth0.com",
            auth0_audience="https://finance-api.example.com",
            auth0_client_id="public-client-id",
        )

        health = TestClient(app).get("/api/health")
        auth_config = TestClient(app).get("/api/auth/config")

        self.assertEqual(health.json(), {"status": "ok", "service": "Finance Advisor"})
        self.assertEqual(auth_config.status_code, 200)
        self.assertTrue(auth_config.json()["data"]["enabled"])
        self.assertEqual(auth_config.json()["data"]["client_id"], "public-client-id")

    @patch(
        "backend.app.main.get_auth_payload",
        return_value={
            "sub": "auth0|alice",
            "name": "Alice Example",
            "preferred_username": "alice",
            "roles": ["admin"],
        },
    )
    def test_auth_identity_exposes_a_display_name_without_replacing_subject(
        self, get_auth_payload
    ):
        response = TestClient(app).get("/api/auth/me")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["data"]["sub"], "auth0|alice")
        self.assertEqual(response.json()["data"]["display_name"], "Alice Example")
        self.assertEqual(response.json()["data"]["username"], "alice")
        self.assertEqual(response.json()["data"]["roles"], ["admin"])

    def test_root_serves_a_login_gate_with_dashboard_hidden(self):
        response = TestClient(app).get("/")

        self.assertEqual(response.status_code, 200)
        self.assertIn('id="authGate"', response.text)
        self.assertIn('<div class="app-shell" hidden>', response.text)
        self.assertIn("Wait for Advisor response..", response.text)

    @patch("backend.app.main.fetch_exchange_rates")
    def test_currency_conversion_endpoint_returns_amount_and_rate(self, fetch_rates):
        fetch_rates.return_value = {"INR": 83.25}

        response = TestClient(app).post(
            "/api/currency/convert",
            json={
                "amount": 10,
                "from_currency": "usd",
                "to_currency": "inr",
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["data"]["rate"], 83.25)
        self.assertEqual(response.json()["data"]["converted_amount"], 832.5)
        fetch_rates.assert_called_once_with("USD")

    @patch("backend.app.main.fetch_exchange_rates", return_value=None)
    def test_currency_conversion_endpoint_reports_unavailable_rates(self, fetch_rates):
        response = TestClient(app).post(
            "/api/currency/convert",
            json={"amount": 10, "from_currency": "USD", "to_currency": "INR"},
        )

        self.assertEqual(response.status_code, 503)
        fetch_rates.assert_called_once_with("USD")

    @patch("backend.app.main.fetch_exchange_rates")
    def test_currency_conversion_endpoint_handles_same_currency_and_invalid_rates(self, fetch_rates):
        client = TestClient(app)
        same_currency = client.post(
            "/api/currency/convert",
            json={"amount": 10, "from_currency": "usd", "to_currency": "USD"},
        )
        self.assertEqual(same_currency.status_code, 200)
        self.assertEqual(same_currency.json()["data"]["rate"], 1)
        fetch_rates.assert_not_called()

        fetch_rates.return_value = {"EUR": 0.92}
        missing_rate = client.post(
            "/api/currency/convert",
            json={"amount": 10, "from_currency": "USD", "to_currency": "INR"},
        )
        self.assertEqual(missing_rate.status_code, 422)

        fetch_rates.return_value = {"INR": "not-a-number"}
        invalid_rate = client.post(
            "/api/currency/convert",
            json={"amount": 10, "from_currency": "USD", "to_currency": "INR"},
        )
        self.assertEqual(invalid_rate.status_code, 502)

    @patch("backend.app.services.api_clients.requests.get")
    @patch("backend.app.services.api_clients.get_settings")
    def test_api_key_endpoint_parses_conversion_rates(self, get_settings, get):
        get_settings.return_value.exchange_rate_api_key = "test-key"
        response = Mock()
        response.json.return_value = {
            "result": "success",
            "conversion_rates": {"USD": 1, "EUR": 0.92},
        }
        get.return_value = response

        rates = fetch_exchange_rates("USD")

        get.assert_called_once_with(
            "https://v6.exchangerate-api.com/v6/test-key/latest/USD",
            timeout=10,
        )
        self.assertEqual(rates, {"USD": 1, "EUR": 0.92})

    @patch("backend.app.services.api_clients.requests.get")
    @patch("backend.app.services.api_clients.get_settings")
    def test_no_key_uses_free_endpoint_rates_shape(self, get_settings, get):
        get_settings.return_value.exchange_rate_api_key = None
        response = Mock()
        response.json.return_value = {
            "result": "success",
            "rates": {"USD": 1, "EUR": 0.92},
        }
        get.return_value = response

        rates = fetch_exchange_rates("USD")

        get.assert_called_once_with(
            "https://open.er-api.com/v6/latest/USD",
            timeout=10,
        )
        self.assertEqual(rates, {"USD": 1, "EUR": 0.92})

    @patch("backend.app.services.api_clients.requests.get", side_effect=requests.RequestException("offline"))
    @patch("backend.app.services.api_clients.get_settings")
    def test_exchange_rate_fetch_returns_none_when_provider_is_unavailable(
        self, get_settings, get
    ):
        get_settings.return_value.exchange_rate_api_key = None

        self.assertIsNone(fetch_exchange_rates("USD"))

    @patch("backend.app.services.api_clients.requests.get")
    @patch("backend.app.services.api_clients.get_settings")
    def test_exchange_rate_fetch_rejects_unsuccessful_or_invalid_payloads(
        self, get_settings, get
    ):
        get_settings.return_value.exchange_rate_api_key = None
        response = Mock()
        get.return_value = response

        response.json.return_value = {"result": "error", "rates": {"EUR": 0.92}}
        self.assertIsNone(fetch_exchange_rates("USD"))
        response.json.return_value = {"result": "success", "rates": ["invalid"]}
        self.assertIsNone(fetch_exchange_rates("USD"))

    @patch("backend.app.services.api_clients.fetch_exchange_rates")
    def test_currency_conversion_handles_same_currency_missing_rate_and_conversion(self, fetch_rates):
        self.assertEqual(convert_currency(10, "USD", "USD"), 10)
        fetch_rates.assert_not_called()

        fetch_rates.side_effect = [None, {"EUR": None}, {"EUR": 0.925}]
        self.assertEqual(convert_currency(10, "USD", "EUR"), 10)
        self.assertEqual(convert_currency(10, "USD", "EUR"), 10)
        self.assertEqual(convert_currency(10, "USD", "EUR"), 9.25)
        self.assertEqual(fetch_rates.call_count, 3)

    @patch("backend.app.services.api_clients.requests.get")
    def test_ip_geolocation_returns_context_and_falls_back_on_provider_errors(self, get):
        response = Mock()
        response.json.return_value = {
            "city": "Pune",
            "country_name": "India",
            "region": "Maharashtra",
            "currency": "INR",
        }
        get.return_value = response

        context = fetch_geolocation_context()
        self.assertEqual(context["city"], "Pune")
        self.assertEqual(context["country"], "India")
        self.assertEqual(context["currency"], "INR")

        get.side_effect = requests.RequestException("offline")
        self.assertEqual(
            fetch_geolocation_context(),
            {"city": None, "country": None, "region": None, "currency": None},
        )

    @patch("backend.app.services.api_clients.requests.get")
    def test_open_meteo_empty_and_failed_lookups_keep_requested_city(self, get):
        response = Mock()
        response.json.return_value = {"results": []}
        get.return_value = response
        expected = {"city": "Pune", "country": None, "region": None, "currency": None}

        self.assertEqual(fetch_geolocation_context("Pune"), expected)
        get.side_effect = requests.RequestException("offline")
        self.assertEqual(fetch_geolocation_context("Pune"), expected)

    @patch("backend.app.services.api_clients.requests.get")
    def test_open_meteo_geocodes_city_and_returns_regional_context(self, get):
        response = Mock()
        response.json.return_value = {
            "results": [{
                "name": "Ahmedabad",
                "admin1": "Gujarat",
                "admin2": "Ahmedabad",
                "country": "India",
                "country_code": "IN",
                "latitude": 23.0225,
                "longitude": 72.5714,
                "timezone": "Asia/Kolkata",
                "population": 5570585,
            }]
        }
        get.return_value = response

        context = fetch_geolocation_context("Ahmedabad, Gujarat")

        get.assert_called_once_with(
            "https://geocoding-api.open-meteo.com/v1/search",
            params={"name": "Ahmedabad, Gujarat", "count": 1, "language": "en"},
            timeout=8,
        )
        self.assertEqual(context["city"], "Ahmedabad")
        self.assertEqual(context["region"], "Gujarat")
        self.assertEqual(context["country"], "India")
        self.assertEqual(context["timezone"], "Asia/Kolkata")
        self.assertEqual(context["source"], "Open-Meteo Geocoding API")

    @patch("backend.app.services.api_clients.requests.get")
    def test_reverse_geocodes_device_coordinates(self, get):
        response = Mock()
        response.json.return_value = {
            "address": {
                "city": "Pune",
                "state": "Maharashtra",
                "country": "India",
            },
            "display_name": "Pune, Maharashtra, India",
        }
        get.return_value = response

        location = reverse_geocode_coordinates(18.5204, 73.8567)

        self.assertEqual(location["city"], "Pune")
        self.assertEqual(location["region"], "Maharashtra")
        self.assertEqual(location["country"], "India")
        get.assert_called_once()

    @patch("backend.app.services.api_clients.requests.get")
    def test_reverse_geocoding_uses_city_level_result_when_county_is_present(self, get):
        response = Mock()
        response.json.return_value = {
            "address": {
                "city_district": "Central District",
                "county": "Pune District",
                "state": "Maharashtra",
                "country": "India",
            },
            "display_name": "Central District, Pune District, India",
        }
        get.return_value = response

        location = reverse_geocode_coordinates(18.5204, 73.8567)

        self.assertEqual(location["city"], "Central District")
        self.assertEqual(location["locality"], "Pune District")
        self.assertEqual(get.call_args.kwargs["params"]["zoom"], 10)

    @patch("backend.app.services.api_clients.requests.get")
    def test_reverse_geocoding_prefers_main_city_over_taluka_area(self, get):
        response = Mock()
        response.json.return_value = {
            "address": {
                "city_district": "Vatva Taluka",
                "state_district": "Ahmedabad",
                "county": "Vatva Taluka",
                "state": "Gujarat",
                "country": "India",
            },
            "display_name": "Vatva Taluka, Ahmedabad, Gujarat, India",
        }
        get.return_value = response

        location = reverse_geocode_coordinates(22.96, 72.65)

        self.assertEqual(location["city"], "Ahmedabad")
        self.assertEqual(location["locality"], "Vatva Taluka")

    @patch("backend.app.services.api_clients.requests.get")
    def test_reverse_geocoding_shows_main_city_and_locality(self, get):
        response = Mock()
        response.json.return_value = {
            "address": {
                "city": "Ahmedabad",
                "suburb": "Sarkhej",
                "state": "Gujarat",
                "country": "India",
            },
            "display_name": "Sarkhej, Ahmedabad, Gujarat, India",
        }
        get.return_value = response

        location = reverse_geocode_coordinates(22.9956, 72.5004)

        self.assertEqual(location["city"], "Ahmedabad")
        self.assertEqual(location["locality"], "Sarkhej")
        self.assertEqual(get.call_args.kwargs["params"]["zoom"], 10)

    @patch("backend.app.services.api_clients.requests.get")
    def test_reverse_geocoding_uses_available_city_aliases_and_rejects_empty_address(self, get):
        response = Mock()
        response.json.return_value = {
            "address": {"town": "Town", "neighbourhood": "Neighbourhood", "country": "India"},
            "display_name": "Town, India",
        }
        get.return_value = response

        location = reverse_geocode_coordinates(1, 2)

        self.assertEqual(location["city"], "Town")
        self.assertEqual(location["locality"], "Neighbourhood")

        response.json.return_value = {"address": {}}
        with self.assertRaises(ValueError):
            reverse_geocode_coordinates(1, 2)

    @patch(
        "backend.app.services.api_clients.requests.get",
        side_effect=requests.RequestException("offline"),
    )
    def test_reverse_geocoding_propagates_provider_errors(self, get):
        with self.assertRaises(requests.RequestException):
            reverse_geocode_coordinates(1, 2)

    @patch("backend.app.main.reverse_geocode_coordinates")
    def test_reverse_location_endpoint_returns_resolved_place(self, reverse_geocode):
        reverse_geocode.return_value = {
            "city": "Pune",
            "region": "Maharashtra",
            "country": "India",
        }

        response = TestClient(app).get(
            "/api/location/reverse",
            params={"latitude": 18.5204, "longitude": 73.8567},
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["data"]["city"], "Pune")

    @patch(
        "backend.app.main.reverse_geocode_coordinates",
        side_effect=ValueError("no address"),
    )
    def test_reverse_location_endpoint_reports_provider_failure(self, reverse_geocode):
        response = TestClient(app).get(
            "/api/location/reverse",
            params={"latitude": 18.5204, "longitude": 73.8567},
        )

        self.assertEqual(response.status_code, 502)
        reverse_geocode.assert_called_once()

    @patch("backend.app.main.get_auth_payload")
    @patch("backend.app.main.save_goals")
    @patch("backend.app.main.save_transactions")
    @patch("backend.app.main.upsert_profile")
    @patch("backend.app.main.agent.process_chat_message")
    def test_chat_endpoint_persists_selected_currency(
        self, process_chat_message, upsert_profile, save_transactions, save_goals,
        get_auth_payload
    ):
        get_auth_payload.return_value = {"sub": "auth0|alice"}
        process_chat_message.return_value = {
            "reply": "Your budget is on track.",
            "data": {"currency": "INR"},
        }

        response = TestClient(app).post(
            "/api/chat",
            json={
                "message": "How are my savings?",
                "session_id": "inr-session",
                "income": 50000,
                "currency": "INR",
                "location": "Pune",
                "goals": [{"name": "Emergency", "target": 10000, "saved": 2500}],
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["data"]["data"]["currency"], "INR")
        upsert_profile.assert_called_once_with("auth0|alice", 50000, "INR", "Pune")
        save_goals.assert_called_once_with(
            "auth0|alice",
            [{"name": "Emergency", "target": 10000.0, "saved": 2500.0}],
        )
        self.assertEqual(process_chat_message.call_args.args[0].session_id, "auth0|alice")
        self.assertEqual(process_chat_message.call_args.args[0].location, "Pune")

    @patch("backend.app.main.get_auth_payload", return_value={"sub": "auth0|alice"})
    @patch("backend.app.main.save_goals")
    @patch("backend.app.main.save_transactions")
    @patch("backend.app.main.upsert_profile")
    @patch("backend.app.main.agent.process_chat_message", return_value={"reply": "Hello."})
    def test_chat_without_goals_skips_goal_persistence(
        self, process_chat_message, upsert_profile, save_transactions, save_goals,
        get_auth_payload
    ):
        response = TestClient(app).post(
            "/api/chat",
            json={"message": "hello", "goals": []},
        )

        self.assertEqual(response.status_code, 200)
        save_goals.assert_not_called()
        self.assertEqual(process_chat_message.call_args.args[0].session_id, "auth0|alice")

    @patch("backend.app.main.get_auth_payload", return_value={"sub": "auth0|alice"})
    @patch("backend.app.main.save_transactions")
    @patch("backend.app.main.upsert_profile")
    @patch("backend.app.main.agent.analyze", return_value={"savings_rate": 50})
    def test_analysis_uses_authenticated_user_instead_of_client_session_id(
        self, analyze, upsert_profile, save_transactions, get_auth_payload
    ):
        response = TestClient(app).post(
            "/api/finance/analyze",
            json={
                "income": 50000,
                "session_id": "auth0|bob",
                "transactions": [],
            },
        )

        self.assertEqual(response.status_code, 200)
        upsert_profile.assert_called_once_with("auth0|alice", 50000, "USD", None)
        save_transactions.assert_called_once_with("auth0|alice", [])
        self.assertEqual(analyze.call_args.args[0].session_id, "auth0|alice")

    @patch("backend.app.main.get_auth_payload", return_value={"sub": "auth0|alice"})
    @patch("backend.app.main.save_goals")
    @patch("backend.app.main.save_transactions")
    @patch("backend.app.main.upsert_profile")
    @patch("backend.app.main.agent.analyze", return_value={"savings_rate": 50})
    def test_analysis_persists_a_submitted_savings_goal(
        self, analyze, upsert_profile, save_transactions, save_goals, get_auth_payload
    ):
        response = TestClient(app).post(
            "/api/finance/analyze",
            json={
                "income": 50000,
                "goal_name": "Emergency",
                "goal_amount": 10000,
                "goal_saved": 2500,
            },
        )

        self.assertEqual(response.status_code, 200)
        save_goals.assert_called_once_with(
            "auth0|alice",
            [{"name": "Emergency", "target": 10000.0, "saved": 2500.0}],
        )
        self.assertEqual(analyze.call_args.args[0].session_id, "auth0|alice")

    @patch("backend.app.main.get_auth_payload", return_value={"sub": "auth0|alice"})
    @patch("backend.app.main.load_session")
    def test_cannot_read_another_users_session(self, load_session, get_auth_payload):
        response = TestClient(app).get("/api/session/auth0|bob")

        self.assertEqual(response.status_code, 404)
        load_session.assert_not_called()

    @patch("backend.app.main.get_auth_payload", return_value={"sub": "auth0|alice"})
    @patch("backend.app.main.load_session", return_value={"income": 50000, "transactions": []})
    def test_can_read_own_session(self, load_session, get_auth_payload):
        response = TestClient(app).get("/api/session/auth0|alice")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["data"]["income"], 50000)
        load_session.assert_called_once_with("auth0|alice")


if __name__ == "__main__":
    unittest.main()
