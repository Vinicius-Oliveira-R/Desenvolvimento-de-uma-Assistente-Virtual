"""Diagnóstico de transporte e rotas, sem login, credenciais ou escrita."""

from dataclasses import dataclass
from urllib.parse import urlsplit, urlunsplit

import httpx

from setup.runtime_config import api_base_url, api_timeout


class ApiDiagnosticError(RuntimeError):
    pass


@dataclass(frozen=True)
class ApiDiagnosticResult:
    health_status: int
    authentication_status: int


def check_backend(
    base_url: str,
    timeout: float = 30,
    *,
    debug: bool = False,
    transport: httpx.BaseTransport | None = None,
) -> ApiDiagnosticResult:
    base_url = api_base_url(base_url, debug=debug)
    timeout = api_timeout(str(timeout))
    parts = urlsplit(base_url)
    health_url = urlunsplit((parts.scheme, parts.netloc, "/health", "", ""))
    try:
        with httpx.Client(
            timeout=timeout, transport=transport, follow_redirects=False,
        ) as client:
            health = client.get(health_url)
            if health.status_code != 200:
                raise ApiDiagnosticError(
                    f"GET /health retornou HTTP {health.status_code}. "
                    "Confira o endereço público e o estado do backend."
                )
            try:
                payload = health.json()
            except ValueError:
                raise ApiDiagnosticError("GET /health não retornou JSON válido.") from None
            if not isinstance(payload, dict) or payload.get("status") != "ok":
                raise ApiDiagnosticError("GET /health retornou um formato inesperado.")

            client.cookies.clear()
            authentication = client.get(f"{base_url}/auth/me")
            if authentication.status_code != 401:
                raise ApiDiagnosticError(
                    f"GET /api/auth/me sem credenciais retornou HTTP {authentication.status_code}; "
                    "era esperado 401. Confira o prefixo /api e a proteção da rota."
                )
            return ApiDiagnosticResult(health.status_code, authentication.status_code)
    except httpx.TimeoutException:
        raise ApiDiagnosticError(
            "A API excedeu o tempo de resposta. Confira os logs do backend e "
            "uma possível inicialização após inatividade. Nenhuma chamada foi repetida."
        ) from None
    except httpx.HTTPError:
        raise ApiDiagnosticError(
            "Não foi possível concluir a conexão HTTP com a API. "
            "Confira FASTAPI_BASE_URL, DNS, TLS e a disponibilidade do backend."
        ) from None
