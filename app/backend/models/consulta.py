from __future__ import annotations

from datetime import datetime, timezone
from enum import StrEnum

from sqlalchemy import ForeignKey, Index, String, text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.backend.core.database import Base


class StatusConsulta(StrEnum):
    AGENDADA = "agendada"
    CANCELADA = "cancelada"
    REALIZADA = "realizada"


CONSULTA_ATIVA = text(f"status <> '{StatusConsulta.CANCELADA}'")


class Consulta(Base):
    __tablename__ = "consultas"
    __table_args__ = (
        Index(
            "uq_consulta_horario_ativa",
            "horario_id",
            unique=True,
            postgresql_where=CONSULTA_ATIVA,
            sqlite_where=CONSULTA_ATIVA,
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    paciente_id: Mapped[int] = mapped_column(ForeignKey("pacientes.id"), nullable=False)
    medico_id: Mapped[int] = mapped_column(ForeignKey("medicos.id"), nullable=False)
    horario_id: Mapped[int] = mapped_column(ForeignKey("horarios.id"), nullable=False)
    data: Mapped[str] = mapped_column(String(30), nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default=StatusConsulta.AGENDADA)
    observacao: Mapped[str | None] = mapped_column(String(500), nullable=True)
    data_criacao: Mapped[str] = mapped_column(
        String(30),
        nullable=False,
        default=lambda: datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
    )
    data_atualizacao: Mapped[str] = mapped_column(
        String(30),
        nullable=False,
        default=lambda: datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        onupdate=lambda: datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
    )

    paciente: Mapped["Paciente"] = relationship(back_populates="consultas")
    medico: Mapped["Medico"] = relationship(back_populates="consultas")
    horario: Mapped["Horario"] = relationship(back_populates="consultas")
