from dataclasses import dataclass
from datetime import date
from typing import Any

import httpx
from django.conf import settings


class ApiError(Exception):
    def __init__(self, mensagem: str, status_code: int | None = None):
        super().__init__(mensagem)
        self.mensagem = mensagem
        self.status_code = status_code


class ApiIndisponivelError(ApiError):
    pass


class CredenciaisInvalidasError(ApiError):
    pass


class SessaoExpiradaError(ApiError):
    pass


@dataclass(frozen=True)
class SessaoApi:
    token: str
    nome: str
    email: str


@dataclass(frozen=True)
class RespostaAssistente:
    texto: str
    perfil: str
    intencao: str
    resultado: str
    contexto: dict[str, Any]

    @classmethod
    def from_json(cls, dados: dict[str, Any]) -> "RespostaAssistente":
        return cls(dados["resposta"], dados["perfil"], dados["intencao"], dados["resultado"], dados["contexto"])


@dataclass(frozen=True)
class ConsultaResumo:
    id: int
    status: str
    data: date
    hora_inicio: str
    hora_fim: str
    medico_nome: str
    especialidade: str

    @classmethod
    def from_json(cls, dados: dict[str, Any]) -> "ConsultaResumo":
        return cls(
            id=dados["id"],
            status=dados["status"],
            data=date.fromisoformat(dados["data"]),
            hora_inicio=dados["hora_inicio"],
            hora_fim=dados["hora_fim"],
            medico_nome=dados["medico_nome"],
            especialidade=dados["especialidade"],
        )

    @property
    def ativa(self) -> bool:
        return self.status == "agendada"


class ClinicaApiClient:
    def __init__(self, base_url: str, timeout: float = 10.0, transport: httpx.MockTransport | None = None):
        self._base_url = base_url
        self._timeout = timeout
        self._transport = transport

    @classmethod
    def from_settings(cls) -> "ClinicaApiClient":
        return cls(settings.FASTAPI_BASE_URL, settings.FASTAPI_TIMEOUT)

    def authenticate(self, email: str, senha: str) -> SessaoApi:
        try:
            with httpx.Client(base_url=self._base_url, timeout=self._timeout, transport=self._transport) as cliente:
                resposta = cliente.post("/auth/login", json={"email": email, "senha": senha})
        except httpx.HTTPError as exc:
            raise ApiIndisponivelError("API de agendamento indisponível.") from exc
        if resposta.status_code in (401, 422):
            raise CredenciaisInvalidasError("Credenciais inválidas.", resposta.status_code)
        self._verificar(resposta)
        dados = resposta.json()
        return SessaoApi(dados["token"], dados["nome"], dados["email"])

    async def send_message(self, token: str, mensagem: str, contexto: dict[str, Any]) -> RespostaAssistente:
        dados = await self._requisitar("POST", "/assistant/chat", token, json={"mensagem": mensagem, "contexto": contexto})
        return RespostaAssistente.from_json(dados)

    async def list_my_appointments(self, token: str) -> list[ConsultaResumo]:
        dados = await self._requisitar("GET", "/consultas/minhas", token)
        return [ConsultaResumo.from_json(item) for item in dados]

    async def _requisitar(self, metodo: str, caminho: str, token: str, **opcoes: Any) -> Any:
        try:
            async with httpx.AsyncClient(
                base_url=self._base_url,
                timeout=self._timeout,
                transport=self._transport,
                headers={"Authorization": f"Bearer {token}"},
            ) as cliente:
                resposta = await cliente.request(metodo, caminho, **opcoes)
        except httpx.HTTPError as exc:
            raise ApiIndisponivelError("API de agendamento indisponível.") from exc
        if resposta.status_code in (401, 403):
            raise SessaoExpiradaError("Sessão expirada na API.", resposta.status_code)
        self._verificar(resposta)
        return resposta.json()

    @staticmethod
    def _verificar(resposta: httpx.Response) -> None:
        if resposta.is_success:
            return
        try:
            detalhe = resposta.json().get("detail", resposta.text)
        except ValueError:
            detalhe = resposta.text
        raise ApiError(str(detalhe), resposta.status_code)
