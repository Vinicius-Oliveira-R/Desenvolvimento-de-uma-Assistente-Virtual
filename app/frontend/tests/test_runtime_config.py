import unittest

from setup.runtime_config import ConfigurationError, api_base_url, api_timeout, debug_enabled, postgres_database


class RuntimeConfigTests(unittest.TestCase):
    def test_debug_default_is_false(self):
        self.assertFalse(debug_enabled())

    def test_debug_accepts_whitespace_and_case(self):
        self.assertTrue(debug_enabled(" TRUE "))
        self.assertFalse(debug_enabled(" FALSE "))

    def test_debug_typo_is_rejected(self):
        with self.assertRaises(ConfigurationError):
            debug_enabled("tru")

    def test_https_api_is_normalized(self):
        self.assertEqual(api_base_url(" https://backend.example.com/api/ "), "https://backend.example.com/api")

    def test_local_api_only_in_debug(self):
        self.assertEqual(api_base_url("http://localhost:8000/api", debug=True), "http://localhost:8000/api")
        with self.assertRaises(ConfigurationError):
            api_base_url("http://localhost:8000/api")

    def test_production_rejects_http(self):
        with self.assertRaises(ConfigurationError):
            api_base_url("http://backend.example.com/api")

    def test_wrong_prefixes_are_rejected(self):
        for suffix in ("", "/docs", "/health", "/auth/login", "/api/api", "/api/../api"):
            with self.subTest(suffix=suffix), self.assertRaises(ConfigurationError):
                api_base_url("https://backend.example.com" + suffix)

    def test_url_secrets_are_not_echoed(self):
        for url in ("https://u:secret@example.com/api", "https://example.com/api?token=secret", "https://example.com/api#secret"):
            with self.subTest(url=url), self.assertRaises(ConfigurationError) as caught:
                api_base_url(url)
            self.assertNotIn("secret", str(caught.exception))

    def test_malformed_url_is_rejected(self):
        for value in ("", "https://[bad/api", "https://example.com:bad/api", "https://example.com:0/api", "https://exa mple.com/api"):
            with self.subTest(value=value), self.assertRaises(ConfigurationError):
                api_base_url(value)

    def test_timeout_default_and_numeric(self):
        self.assertEqual(api_timeout(), 30)
        self.assertEqual(api_timeout("30.5"), 30.5)

    def test_timeout_invalid_is_rejected(self):
        for value in ("0", "-1", "nan", "inf", "121", "30 segundos", ""):
            with self.subTest(value=value), self.assertRaises(ConfigurationError):
                api_timeout(value)

    def test_postgres_neon_security_is_preserved(self):
        db = postgres_database("postgresql+psycopg://u:p@host.example/neondb?sslmode=verify-full&channel_binding=require")
        self.assertEqual(db["ENGINE"], "django.db.backends.postgresql")
        self.assertEqual(db["OPTIONS"]["sslmode"], "verify-full")
        self.assertEqual(db["OPTIONS"]["channel_binding"], "require")
        self.assertEqual(db["CONN_MAX_AGE"], 0)

    def test_postgres_tls_default(self):
        self.assertEqual(postgres_database("postgresql://u:p@host/db")["OPTIONS"]["sslmode"], "require")

    def test_postgres_encoded_credentials(self):
        db = postgres_database("postgres://u%40x:p%40ss%3Aword@host:5433/my%2Ddb")
        self.assertEqual((db["USER"], db["PASSWORD"], db["NAME"], db["PORT"]), ("u@x", "p@ss:word", "my-db", 5433))

    def test_postgres_incomplete_or_sqlite_is_rejected(self):
        for value in ("", "sqlite:///db.sqlite3", "postgresql://u:p@host", "postgresql:///db", "postgresql://u@host/db"):
            with self.subTest(value=value), self.assertRaises(ConfigurationError):
                postgres_database(value)

    def test_postgres_security_cannot_be_downgraded_in_production(self):
        with self.assertRaises(ConfigurationError):
            postgres_database("postgresql://u:p@host/db?sslmode=disable")
        self.assertEqual(postgres_database("postgresql://u:p@localhost/db?sslmode=disable", debug=True)["OPTIONS"]["sslmode"], "disable")

    def test_postgres_duplicate_or_unknown_parameters(self):
        for query in ("sslmode=require&sslmode=disable", "unknown=secret", "secret", "channel_binding=typo", "connect_timeout=0"):
            with self.subTest(query=query), self.assertRaises(ConfigurationError) as caught:
                postgres_database("postgresql://u:secret@host/db?" + query)
            self.assertNotIn("secret", str(caught.exception))

    def test_postgres_connect_timeout(self):
        self.assertEqual(postgres_database("postgresql://u:p@host/db?connect_timeout=20")["OPTIONS"]["connect_timeout"], 20)


if __name__ == "__main__":
    unittest.main()
