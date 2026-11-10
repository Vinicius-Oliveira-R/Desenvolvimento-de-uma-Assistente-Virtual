import httpx
from django.contrib.auth import SESSION_KEY, get_user_model
from django.test import TestCase
from django.urls import reverse

from assistant.tests import ApiFalsaMixin


class LoginDeploymentRegressionTests(ApiFalsaMixin, TestCase):
    credentials = {"username": "user@example.com", "password": "private-test-password"}

    def test_api_http_failures_are_logged_without_response_body(self):
        for status in (302, 404, 429, 500, 503):
            with self.subTest(status=status):
                self.usar_api(lambda _, code=status: httpx.Response(code, text="private-response-token"))
                with self.assertLogs("assistant.login", level="WARNING") as logs:
                    response = self.client.post(reverse("login"), self.credentials)
                self.assertContains(response, "indisponível no momento")
                output = " ".join(logs.output)
                self.assertIn(f"status={status}", output)
                self.assertNotIn("private", output)
                self.assertNotIn("user@example.com", output)
                self.assertNotIn(SESSION_KEY, self.client.session)

    def test_timeout_is_logged_without_credentials_or_retry(self):
        def timeout(request):
            raise httpx.ReadTimeout("private-test-password", request=request)

        requests = self.usar_api(timeout)
        with self.assertLogs("assistant.login", level="WARNING") as logs:
            response = self.client.post(reverse("login"), self.credentials)
        self.assertContains(response, "indisponível no momento")
        self.assertEqual(len(requests), 1)
        self.assertIn("causa=ReadTimeout", logs.output[0])
        self.assertNotIn("private-test-password", logs.output[0])

    def test_success_with_invalid_json_does_not_return_500(self):
        self.usar_api(lambda _: httpx.Response(200, text="<html>private-error</html>"))
        with self.assertLogs("assistant.login", level="WARNING"):
            response = self.client.post(reverse("login"), self.credentials)
        self.assertContains(response, "indisponível no momento")
        self.assertNotIn(SESSION_KEY, self.client.session)
        self.assertFalse(get_user_model().objects.exists())

    def test_success_with_missing_token_does_not_create_user(self):
        self.usar_api(lambda _: httpx.Response(200, json={"nome": "Teste", "email": "user@example.com", "papel": "gestor"}))
        with self.assertLogs("assistant.login", level="WARNING"):
            response = self.client.post(reverse("login"), self.credentials)
        self.assertContains(response, "indisponível no momento")
        self.assertFalse(get_user_model().objects.exists())

    def test_invalid_credentials_remain_distinct(self):
        for status in (401, 422):
            with self.subTest(status=status):
                self.usar_api(lambda _, code=status: httpx.Response(code, json={"detail": "Credenciais inválidas"}))
                with self.assertNoLogs("assistant.login", level="WARNING"):
                    response = self.client.post(reverse("login"), self.credentials)
                self.assertContains(response, "E-mail ou senha incorretos.")
                self.assertNotIn(SESSION_KEY, self.client.session)

    def test_valid_login_keeps_api_prefix_and_session(self):
        requests = self.usar_api(lambda _: httpx.Response(200, json={
            "id": 1, "nome": "Teste", "email": "user@example.com", "papel": "gestor", "token": "test-jwt",
        }))
        with self.assertNoLogs("assistant.login", level="WARNING"):
            response = self.client.post(reverse("login"), self.credentials)
        self.assertEqual(response.status_code, 302)
        self.assertEqual(str(requests[0].url), "http://api.teste/api/auth/login")
        self.assertIn(SESSION_KEY, self.client.session)
