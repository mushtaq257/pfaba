import unittest

from backend.app.config import Settings, get_settings


class SettingsTests(unittest.TestCase):
    def test_auth0_is_enabled_only_when_required_values_are_present(self):
        complete = Settings(
            auth0_domain="finance-test.auth0.com",
            auth0_client_id="client-id",
            auth0_audience="https://finance-api.example.com",
        )
        missing_client = Settings(
            auth0_domain="finance-test.auth0.com",
            auth0_client_id="",
            auth0_audience="https://finance-api.example.com",
        )

        self.assertTrue(complete.auth0_enabled)
        self.assertFalse(missing_client.auth0_enabled)

    def test_get_settings_caches_the_settings_instance(self):
        get_settings.cache_clear()
        try:
            first = get_settings()
            self.assertIs(get_settings(), first)
        finally:
            get_settings.cache_clear()

    def test_auth0_management_is_enabled_only_with_dedicated_m2m_credentials(self):
        complete = Settings(
            auth0_domain="finance-test.auth0.com",
            auth0_management_client_id="management-client",
            auth0_management_client_secret="management-secret",
        )
        missing_secret = Settings(
            auth0_domain="finance-test.auth0.com",
            auth0_management_client_id="management-client",
            auth0_management_client_secret="",
        )

        self.assertTrue(complete.auth0_management_enabled)
        self.assertFalse(missing_secret.auth0_management_enabled)

    def test_database_url_can_be_configured_for_postgresql(self):
        settings = Settings(database_url="postgresql://user:password@db.example/finance")

        self.assertEqual(
            settings.database_url,
            "postgresql://user:password@db.example/finance",
        )


if __name__ == "__main__":
    unittest.main()
