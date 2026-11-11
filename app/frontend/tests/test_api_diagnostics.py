import unittest

import httpx

from assistant.api_diagnostics import ApiDiagnosticError, check_backend
from setup.runtime_config import ConfigurationError


class ApiDiagnosticTests(unittest.TestCase):
    def run_probe(self, handler, base_url="https://backend.example.test/api"):
        self.requests = []

        def dispatch(request):
            self.requests.append(request)
            return handler(request)

        return check_backend(base_url, transport=httpx.MockTransport(dispatch))

    def test_health_and_protected_prefix_are_checked_without_credentials(self):
        def response(request):
            if request.url.path == "/health":
                return httpx.Response(200, json={"status": "ok"})
            return httpx.Response(401)

        result = self.run_probe(response, "https://backend.example.test/api/")
        self.assertEqual((result.health_status, result.authentication_status), (200, 401))
        self.assertEqual([r.url.path for r in self.requests], ["/health", "/api/auth/me"])
        for request in self.requests:
            self.assertEqual(request.method, "GET")
            self.assertEqual(request.content, b"")
            self.assertNotIn("authorization", request.headers)
            self.assertNotIn("cookie", request.headers)

    def test_health_cookie_is_not_forwarded_to_authentication_probe(self):
        def response(request):
            if request.url.path == "/health":
                return httpx.Response(200, json={"status": "ok"}, headers={"set-cookie": "session=private; Path=/"})
            self.assertNotIn("cookie", request.headers)
            return httpx.Response(401)

        self.run_probe(response)

    def test_failure_on_health_stops_without_reading_response_body(self):
        for code in (301, 404, 429, 500, 503):
            with self.subTest(code=code), self.assertRaises(ApiDiagnosticError) as caught:
                self.run_probe(lambda _: httpx.Response(code, text="private-response"))
            self.assertIn(str(code), str(caught.exception))
            self.assertNotIn("private", str(caught.exception))
            self.assertEqual(len(self.requests), 1)

    def test_redirect_is_not_followed(self):
        with self.assertRaises(ApiDiagnosticError):
            self.run_probe(lambda _: httpx.Response(302, headers={"location": "https://other.test/private"}))
        self.assertEqual(len(self.requests), 1)

    def test_invalid_health_json_is_sanitized(self):
        with self.assertRaises(ApiDiagnosticError) as caught:
            self.run_probe(lambda _: httpx.Response(200, text="private-not-json"))
        self.assertNotIn("private", str(caught.exception))
        self.assertEqual(len(self.requests), 1)

    def test_unexpected_health_shape_is_rejected(self):
        for body in (None, [], "ok", {}, {"status": "unhealthy"}):
            with self.subTest(body=body), self.assertRaises(ApiDiagnosticError):
                self.run_probe(lambda _: httpx.Response(200, json=body))
            self.assertEqual(len(self.requests), 1)

    def test_missing_or_unprotected_auth_route_does_not_pass(self):
        for code in (200, 302, 403, 404, 500, 503):
            def response(request):
                if request.url.path == "/health":
                    return httpx.Response(200, json={"status": "ok"})
                return httpx.Response(code, text="private-response-token")

            with self.subTest(code=code), self.assertRaises(ApiDiagnosticError) as caught:
                self.run_probe(response)
            self.assertIn(str(code), str(caught.exception))
            self.assertNotIn("private", str(caught.exception))
            self.assertEqual(len(self.requests), 2)

    def test_timeout_is_sanitized_and_not_retried(self):
        def response(request):
            raise httpx.ReadTimeout("private-secret", request=request)

        with self.assertRaises(ApiDiagnosticError) as caught:
            self.run_probe(response)
        self.assertIn("tempo", str(caught.exception))
        self.assertNotIn("private", str(caught.exception))
        self.assertEqual(len(self.requests), 1)

    def test_connection_failure_is_sanitized(self):
        def response(request):
            raise httpx.ConnectError("private-host-password", request=request)

        with self.assertRaises(ApiDiagnosticError) as caught:
            self.run_probe(response)
        self.assertIn("conexão", str(caught.exception))
        self.assertNotIn("private", str(caught.exception))

    def test_invalid_configuration_performs_no_network_call(self):
        for url in ("", "http://localhost:8000/api", "https://user:private@host/api", "https://host/docs"):
            with self.subTest(url=url), self.assertRaises(ConfigurationError):
                self.run_probe(lambda _: self.fail("Unexpected network request"), url)
            self.assertEqual(self.requests, [])

    def test_timeout_after_health_does_not_retry(self):
        def response(request):
            if request.url.path == "/health":
                return httpx.Response(200, json={"status": "ok"})
            raise httpx.ReadTimeout("private", request=request)

        with self.assertRaises(ApiDiagnosticError):
            self.run_probe(response)
        self.assertEqual(len(self.requests), 2)


if __name__ == "__main__":
    unittest.main()
