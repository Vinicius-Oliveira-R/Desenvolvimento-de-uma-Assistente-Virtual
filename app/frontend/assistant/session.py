from typing import Any

from django.contrib.sessions.backends.base import SessionBase


class SessaoAssistente:
    """Estado da conversa guardado na sessão do servidor; expira junto com a sessão."""

    TOKEN = "api_token"
    CONTEXTO = "assistente_contexto"
    PAPEL = "api_papel"
    ABERTURA = "assistente_abertura"

    def __init__(self, session: SessionBase):
        self._session = session

    @classmethod
    def iniciar(cls, session: SessionBase, token: str, papel: str) -> None:
        session[cls.TOKEN] = token
        session[cls.PAPEL] = papel
        session.pop(cls.CONTEXTO, None)
        session.pop(cls.ABERTURA, None)

    async def token(self) -> str | None:
        return await self._session.aget(self.TOKEN)

    async def papel(self) -> str | None:
        return await self._session.aget(self.PAPEL)

    async def contexto(self) -> dict[str, Any]:
        return await self._session.aget(self.CONTEXTO, {})

    async def salvar_contexto(self, contexto: dict[str, Any]) -> None:
        await self._session.aset(self.CONTEXTO, contexto)

    async def encerrar_proposta(self) -> dict[str, Any]:
        """ "Novo agendamento": descarta a pergunta pendente e mantém as preferências de explicação."""
        contexto = {**await self.contexto(), "acao_pendente": None}
        await self.salvar_contexto(contexto)
        return contexto

    async def guardar_abertura(self, mensagem: str, resposta: dict[str, Any]) -> None:
        await self._session.aset(self.ABERTURA, {"mensagem": mensagem, "resposta": resposta})

    async def retirar_abertura(self) -> dict[str, Any] | None:
        abertura = await self._session.aget(self.ABERTURA)
        if abertura is not None:
            await self._session.apop(self.ABERTURA)
        return abertura
