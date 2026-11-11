from io import StringIO
from unittest import mock

from django.core.management import call_command, CommandError
from django.test import SimpleTestCase, override_settings

from assistant.api_diagnostics import ApiDiagnosticError, ApiDiagnosticResult


@override_settings(FASTAPI_BASE_URL="https://backend.example.test/api", FASTAPI_TIMEOUT=30)
class CheckApiCommandTests(SimpleTestCase):
    @mock.patch("assistant.management.commands.check_api.check_backend")
    def test_command_uses_effective_configuration_without_database(self, probe):
        probe.return_value = ApiDiagnosticResult(200, 401)
        output = StringIO()
        call_command("check_api", stdout=output)
        probe.assert_called_once_with("https://backend.example.test/api", 30, debug=False)
        self.assertIn("/health=200", output.getvalue())
        self.assertIn("/api/auth/me sem credenciais=401", output.getvalue())
        self.assertIn("não valida senha", output.getvalue())

    @mock.patch("assistant.management.commands.check_api.check_backend")
    def test_command_failure_sets_unsuccessful_exit(self, probe):
        probe.side_effect = ApiDiagnosticError("A API excedeu o tempo de resposta.")
        with self.assertRaisesMessage(CommandError, "tempo de resposta"):
            call_command("check_api", stdout=StringIO())
