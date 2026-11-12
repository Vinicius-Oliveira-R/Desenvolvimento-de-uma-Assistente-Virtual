from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from assistant.api_diagnostics import ApiDiagnosticError, check_backend
from setup.runtime_config import ConfigurationError


class Command(BaseCommand):
    help = "Verifica /health e /api/auth/me sem enviar credenciais nem consultar o banco."
    requires_system_checks = []

    def handle(self, *args, **options):
        try:
            result = check_backend(
                settings.FASTAPI_BASE_URL,
                settings.FASTAPI_TIMEOUT,
                debug=settings.DEBUG,
            )
        except (ConfigurationError, ApiDiagnosticError) as exc:
            raise CommandError(str(exc)) from None
        self.stdout.write(self.style.SUCCESS(
            f"Comunicação verificada: /health={result.health_status}; "
            f"/api/auth/me sem credenciais={result.authentication_status}."
        ))
        self.stdout.write(
            "Este teste não valida senha, existência de usuários, banco de dados "
            "ou sessão autenticada."
        )
