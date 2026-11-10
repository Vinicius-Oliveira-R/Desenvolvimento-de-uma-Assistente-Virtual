"""Validação de configuração sem acesso à rede ou ao banco."""

import math
from urllib.parse import parse_qsl, unquote, urlsplit


class ConfigurationError(ValueError):
    pass


def debug_enabled(value: str = "false") -> bool:
    normalized = value.strip().lower()
    if normalized not in {"true", "false"}:
        raise ConfigurationError("DJANGO_DEBUG deve ser true ou false.")
    return normalized == "true"


def api_base_url(value: str, *, debug: bool = False) -> str:
    value = value.strip()
    try:
        url = urlsplit(value)
        port = url.port
    except ValueError:
        raise ConfigurationError("FASTAPI_BASE_URL contém uma URL inválida.") from None
    if (
        not value
        or any(char.isspace() for char in value)
        or url.scheme not in {"http", "https"}
        or not url.hostname
        or url.username is not None
        or url.password is not None
        or url.query
        or url.fragment
        or port == 0
    ):
        raise ConfigurationError("FASTAPI_BASE_URL deve conter somente a URL da API, sem credenciais ou parâmetros.")
    if url.path.rstrip("/") != "/api":
        raise ConfigurationError("FASTAPI_BASE_URL deve terminar em /api, não /docs, /health ou /auth/login.")
    if not debug and (
        url.scheme != "https"
        or url.hostname.lower() in {"localhost", "127.0.0.1", "0.0.0.0", "::1"}
    ):
        raise ConfigurationError("FASTAPI_BASE_URL deve usar o endereço HTTPS do backend em produção.")
    return value.rstrip("/")


def api_timeout(value: str = "30") -> float:
    try:
        result = float(value)
    except (TypeError, ValueError):
        raise ConfigurationError("FASTAPI_TIMEOUT deve ser um número positivo em segundos.") from None
    if not math.isfinite(result) or not 0 < result <= 120:
        raise ConfigurationError("FASTAPI_TIMEOUT deve ser maior que zero e no máximo 120 segundos.")
    return result


def postgres_database(value: str, *, debug: bool = False) -> dict:
    try:
        url = urlsplit(value.strip())
        port = url.port
        pairs = parse_qsl(url.query, keep_blank_values=True, strict_parsing=True)
    except ValueError:
        raise ConfigurationError("DATABASE_URL contém uma conexão PostgreSQL inválida.") from None
    if (
        url.scheme not in {"postgres", "postgresql", "postgresql+psycopg"}
        or not url.hostname
        or not url.username
        or not url.password
        or not url.path.strip("/")
        or url.fragment
        or port == 0
        or any(char.isspace() for char in value.strip())
    ):
        raise ConfigurationError("DATABASE_URL deve conter uma conexão PostgreSQL completa; não há fallback para SQLite.")
    allowed = {
        "sslmode", "sslrootcert", "sslcert", "sslkey", "channel_binding",
        "connect_timeout", "application_name", "options",
    }
    options = dict(pairs)
    if len(options) != len(pairs) or set(options) - allowed:
        raise ConfigurationError("DATABASE_URL contém parâmetros duplicados ou não suportados.")
    options.setdefault("sslmode", "require")
    if options["sslmode"] not in {"disable", "allow", "prefer", "require", "verify-ca", "verify-full"}:
        raise ConfigurationError("O sslmode de DATABASE_URL é inválido.")
    if not debug and options["sslmode"] not in {"require", "verify-ca", "verify-full"}:
        raise ConfigurationError("DATABASE_URL deve exigir TLS em produção.")
    if "channel_binding" in options and options["channel_binding"] not in {"disable", "prefer", "require"}:
        raise ConfigurationError("O channel_binding de DATABASE_URL é inválido.")
    try:
        connect_timeout = int(options.get("connect_timeout", "15"))
    except ValueError:
        raise ConfigurationError("connect_timeout deve ser um inteiro entre 1 e 120 segundos.") from None
    if not 1 <= connect_timeout <= 120:
        raise ConfigurationError("connect_timeout deve ser um inteiro entre 1 e 120 segundos.")
    options["connect_timeout"] = connect_timeout
    return {
        "ENGINE": "django.db.backends.postgresql",
        "NAME": unquote(url.path.lstrip("/")),
        "USER": unquote(url.username),
        "PASSWORD": unquote(url.password),
        "HOST": url.hostname,
        "PORT": port or 5432,
        "OPTIONS": options,
        "CONN_MAX_AGE": 0,
    }
