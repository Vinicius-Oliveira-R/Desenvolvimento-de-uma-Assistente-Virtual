from typing import Any

from django.contrib.sessions.backends.base import SessionBase


class SessaoAssistente:
    TOKEN = "api_token"
    CONTEXTO = "assistente_contexto"

    def __init__(self, session: SessionBase):
        self._session = session

    @classmethod
    def iniciar(cls, session: SessionBase, token: str) -> None:
        session[cls.TOKEN] = token
        session.pop(cls.CONTEXTO, None)

    async def token(self) -> str | None:
        return await self._session.aget(self.TOKEN)

    async def contexto(self) -> dict[str, Any]:
        return await self._session.aget(self.CONTEXTO, {})

    async def salvar_contexto(self, contexto: dict[str, Any]) -> None:
        await self._session.aset(self.CONTEXTO, contexto)
