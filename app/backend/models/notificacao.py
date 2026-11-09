from __future__ import annotations

from datetime import datetime, timezone
from enum import StrEnum

from sqlalchemy import ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.backend.core.database import Base


class TipoNotificacao(StrEnum):
    REAGENDAMENTO_PENDENTE = "reagendamento_pendente"
    CANCELAMENTO_PENDENTE = "cancelamento_pendente"
    AVISO = "aviso"


class StatusNotificacao(StrEnum):
    PENDENTE = "pendente"
    ACEITO = "aceito"
    RECUSADO = "recusado"


SOLICITACOES = (TipoNotificacao.REAGENDAMENTO_PENDENTE, TipoNotificacao.CANCELAMENTO_PENDENTE)


def agora_utc() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


class Notificacao(Base):
    __tablename__ = "notificacoes"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    usuario_destino_id: Mapped[int] = mapped_column(ForeignKey("usuarios.id"), index=True, nullable=False)
    consulta_id: Mapped[int] = mapped_column(ForeignKey("consultas.id"), index=True, nullable=False)
    solicitante_id: Mapped[int | None] = mapped_column(ForeignKey("usuarios.id"), nullable=True)
    horario_novo_id: Mapped[int | None] = mapped_column(ForeignKey("horarios.id"), nullable=True)
    tipo: Mapped[str] = mapped_column(String(30), nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default=StatusNotificacao.PENDENTE)
    mensagem: Mapped[str] = mapped_column(String(500), nullable=False)
    criado_em: Mapped[str] = mapped_column(String(30), nullable=False, default=agora_utc)
    respondido_em: Mapped[str | None] = mapped_column(String(30), nullable=True)

    consulta: Mapped["Consulta"] = relationship()
    horario_novo: Mapped["Horario | None"] = relationship()

    @property
    def e_solicitacao(self) -> bool:
        return self.tipo in SOLICITACOES
