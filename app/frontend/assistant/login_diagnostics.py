"""Diagnóstico do login sem credenciais, tokens ou conteúdo das respostas."""

import logging
from typing import Any

logger = logging.getLogger("assistant.login")


def log_login_failure(error: Exception, status_code: int | None = None) -> None:
    cause = error.__cause__ or error
    logger.warning(
        "Falha no login via FastAPI: status=%s causa=%s",
        status_code if isinstance(status_code, int) else "sem_resposta",
        type(cause).__name__,
    )


def validate_login_payload(payload: Any) -> dict[str, str]:
    fields = ("token", "nome", "email", "papel")
    if not isinstance(payload, dict) or any(
        not isinstance(payload.get(field), str) or not payload[field].strip()
        for field in fields
    ):
        raise ValueError("Resposta de autenticação inválida.")
    if payload["papel"] not in {"gestor", "admin", "medico", "paciente"}:
        raise ValueError("Resposta de autenticação inválida.")
    if len(payload["token"]) > 8192 or any(char.isspace() for char in payload["token"]):
        raise ValueError("Resposta de autenticação inválida.")
    return {field: payload[field] for field in fields}
