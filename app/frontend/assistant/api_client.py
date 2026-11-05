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


class SessaoExpiradaError(Exception):
    pass


class PermissaoNegadaError(ApiError):
    pass


@dataclass(frozen=True)
class SessaoApi:
    token: str
    nome: str
    email: str
    papel: str


@dataclass(frozen=True)
class Perfil:
    papel: str
    papeis_cadastraveis: tuple[str, ...]
    medico_id: int | None = None

    @classmethod
    def from_json(cls, dados: dict[str, Any]) -> "Perfil":
        return cls(dados["papel"], tuple(dados["papeis_cadastraveis"]), dados.get("medico_id"))


@dataclass(frozen=True)
class PacienteResumo:
    id: int
    nome: str
    cpf: str
    data_nascimento: date
    telefone: str

    @classmethod
    def from_json(cls, dados: dict[str, Any]) -> "PacienteResumo":
        return cls(
            dados["id"], dados["nome"], dados["cpf"], date.fromisoformat(dados["data_nascimento"]), dados["telefone"]
        )

    @property
    def cpf_formatado(self) -> str:
        return f"{self.cpf[:3]}.{self.cpf[3:6]}.{self.cpf[6:9]}-{self.cpf[9:]}"


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


@dataclass(frozen=True)
class MedicoResumo:
    id: int
    nome: str
    especialidade: str

    @classmethod
    def from_json(cls, dados: dict[str, Any]) -> "MedicoResumo":
        return cls(dados["id"], dados["nome"], dados["especialidade"])


@dataclass(frozen=True)
class HorarioLivre:
    id: int
    hora_inicio: str
    hora_fim: str

    @classmethod
    def from_json(cls, dados: dict[str, Any]) -> "HorarioLivre":
        return cls(dados["id"], dados["hora_inicio"], dados["hora_fim"])


@dataclass(frozen=True)
class ConsultaAgendada:
    id: int
    status: str
    data: date
    hora_inicio: str
    hora_fim: str
    medico_id: int
    medico_nome: str
    especialidade: str
    paciente_nome: str
    observacao: str | None

    @classmethod
    def from_json(cls, dados: dict[str, Any]) -> "ConsultaAgendada":
        return cls(
            id=dados["id"],
            status=dados["status"],
            data=date.fromisoformat(dados["data"]),
            hora_inicio=dados["hora_inicio"],
            hora_fim=dados["hora_fim"],
            medico_id=dados["medico_id"],
            medico_nome=dados["medico_nome"],
            especialidade=dados["especialidade"],
            paciente_nome=dados["paciente_nome"],
            observacao=dados.get("observacao"),
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
        return SessaoApi(dados["token"], dados["nome"], dados["email"], dados["papel"])

    async def send_message(self, token: str, mensagem: str, contexto: dict[str, Any]) -> RespostaAssistente:
        dados = await self._requisitar("POST", "/assistant/chat", token, json={"mensagem": mensagem, "contexto": contexto})
        return RespostaAssistente.from_json(dados)

    async def list_my_appointments(self, token: str) -> list[ConsultaResumo]:
        dados = await self._requisitar("GET", "/consultas/minhas", token)
        return [ConsultaResumo.from_json(item) for item in dados]

    async def get_profile(self, token: str) -> Perfil:
        return Perfil.from_json(await self._requisitar("GET", "/auth/me", token))

    async def list_specialties(self, token: str) -> list[str]:
        return await self._requisitar("GET", "/medicos/especialidades", token)

    async def register_user(self, token: str, dados: dict[str, Any]) -> dict[str, Any]:
        return await self._requisitar("POST", "/auth/register", token, json=dados)

    async def list_patients(self, token: str) -> list[PacienteResumo]:
        return [PacienteResumo.from_json(item) for item in await self._requisitar("GET", "/pacientes", token)]

    async def list_appointments(self, token: str, filtros: dict[str, str]) -> list[ConsultaAgendada]:
        dados = await self._requisitar("GET", "/consultas", token, params=filtros)
        return [ConsultaAgendada.from_json(item) for item in dados]

    async def get_appointment(self, token: str, consulta_id: int) -> ConsultaAgendada:
        return ConsultaAgendada.from_json(await self._requisitar("GET", f"/consultas/{consulta_id}", token))

    async def create_appointment(self, token: str, dados: dict[str, Any]) -> dict[str, Any]:
        return await self._requisitar("POST", "/consultas", token, json=dados)

    async def update_appointment(self, token: str, consulta_id: int, dados: dict[str, Any]) -> dict[str, Any]:
        return await self._requisitar("PUT", f"/consultas/{consulta_id}", token, json=dados)

    async def cancel_appointment(self, token: str, consulta_id: int) -> dict[str, Any]:
        return await self._requisitar("DELETE", f"/consultas/{consulta_id}", token, json={"confirmado": True})

    async def list_doctors(self, token: str) -> list[MedicoResumo]:
        return [MedicoResumo.from_json(item) for item in await self._requisitar("GET", "/medicos", token)]

    async def list_free_slots(self, token: str, medico_id: int, data: date) -> list[HorarioLivre]:
        filtros = {"medico_id": medico_id, "data": data.isoformat(), "disponivel": "true"}
        dados = await self._requisitar("GET", "/horarios", token, params=filtros)
        return [HorarioLivre.from_json(item) for item in dados]

    async def release_slots(self, token: str, dados: dict[str, Any]) -> dict[str, int]:
        return await self._requisitar("POST", "/horarios/lote", token, json=dados)

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
        if resposta.status_code == 401:
            raise SessaoExpiradaError("Sessão expirada na API.")
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
        if isinstance(detalhe, list):
            detalhe = "; ".join(str(erro.get("msg", erro)) for erro in detalhe)
        erro = PermissaoNegadaError if resposta.status_code == 403 else ApiError
        raise erro(str(detalhe), resposta.status_code)
