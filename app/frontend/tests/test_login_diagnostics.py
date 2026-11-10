import unittest

from assistant.login_diagnostics import log_login_failure, validate_login_payload


class LoginDiagnosticsTests(unittest.TestCase):
    def test_valid_session(self):
        data = {"id": 1, "nome": "Teste", "email": "user@example.com", "papel": "gestor", "token": "jwt-test"}
        self.assertEqual(validate_login_payload(data)["papel"], "gestor")
        self.assertNotIn("id", validate_login_payload(data))

    def test_all_existing_roles(self):
        for role in ("gestor", "admin", "medico", "paciente"):
            with self.subTest(role=role):
                self.assertEqual(validate_login_payload({"nome": "Teste", "email": "user@example.com", "papel": role, "token": "jwt"})["papel"], role)

    def test_invalid_body_types(self):
        for data in (None, [], "html", 1, {}):
            with self.subTest(data=data), self.assertRaises(ValueError):
                validate_login_payload(data)

    def test_missing_empty_and_wrong_type_fields(self):
        valid = {"nome": "Teste", "email": "user@example.com", "papel": "gestor", "token": "jwt"}
        for key in valid:
            for value in (None, "", " ", 1, []):
                with self.subTest(key=key, value=value), self.assertRaises(ValueError):
                    validate_login_payload({**valid, key: value})

    def test_unknown_role_is_rejected(self):
        with self.assertRaises(ValueError):
            validate_login_payload({"nome": "Teste", "email": "user@example.com", "papel": "superuser", "token": "jwt"})

    def test_invalid_token_is_rejected(self):
        for token in ("token with spaces", "x" * 8193):
            with self.subTest(length=len(token)), self.assertRaises(ValueError):
                validate_login_payload({"nome": "Teste", "email": "user@example.com", "papel": "gestor", "token": token})

    def test_log_does_not_contain_exception_message(self):
        with self.assertLogs("assistant.login", level="WARNING") as logs:
            log_login_failure(ValueError("senha-secreta token-secreto email@example.com"), 503)
        output = " ".join(logs.output)
        self.assertIn("status=503", output)
        self.assertIn("causa=ValueError", output)
        self.assertNotIn("secreta", output)
        self.assertNotIn("secreto", output)
        self.assertNotIn("email@example.com", output)

    def test_log_reports_cause_without_traceback(self):
        outer = RuntimeError("secret outer")
        outer.__cause__ = TimeoutError("https://secret:secret@example.com")
        with self.assertLogs("assistant.login", level="WARNING") as logs:
            log_login_failure(outer)
        self.assertIn("status=sem_resposta causa=TimeoutError", logs.output[0])
        self.assertNotIn("secret", logs.output[0])
        self.assertIsNone(logs.records[0].exc_info)


if __name__ == "__main__":
    unittest.main()
