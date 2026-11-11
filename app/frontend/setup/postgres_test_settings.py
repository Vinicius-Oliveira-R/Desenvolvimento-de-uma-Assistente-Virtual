"""Testes em PostgreSQL local descartável. Nunca usar no Render ou com Neon."""

import os

from .test_settings import *  # noqa: F403
from .runtime_config import ConfigurationError, postgres_database

_database = postgres_database(os.environ.get("TEST_POSTGRES_URL", ""), debug=True)
if _database["HOST"] not in {"localhost", "127.0.0.1", "::1"} or _database["NAME"] != "frontend_ci":
    raise ConfigurationError("Os testes PostgreSQL exigem banco local descartável chamado frontend_ci.")
if _database["OPTIONS"].keys() - {"sslmode", "connect_timeout"}:
    raise ConfigurationError("Não são permitidos parâmetros adicionais na conexão PostgreSQL de teste.")
DATABASES = {"default": _database}
