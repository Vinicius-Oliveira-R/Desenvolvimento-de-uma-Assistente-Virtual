from __future__ import annotations

from datetime import datetime, timezone
from enum import StrEnum

from sqlalchemy import Enum, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.backend.core.database import Base


class PapelUsuario(StrEnum):
    GESTOR = "gestor"
    ADMIN = "admin"
    MEDICO = "medico"
    PACIENTE = "paciente"

    def pode_cadastrar(self, papel: PapelUsuario) -> bool:
        return papel in PAPEIS_CADASTRAVEIS[self]


# O gestor não aparece como alvo em nenhum perfil: ninguém o cadastra pela API, nem outro gestor.
PAPEIS_CADASTRAVEIS: dict[PapelUsuario, frozenset[PapelUsuario]] = {
    PapelUsuario.GESTOR: frozenset({PapelUsuario.MEDICO, PapelUsuario.ADMIN}),
    PapelUsuario.MEDICO: frozenset({PapelUsuario.MEDICO, PapelUsuario.ADMIN, PapelUsuario.PACIENTE}),
    PapelUsuario.ADMIN: frozenset({PapelUsuario.ADMIN, PapelUsuario.PACIENTE}),
    PapelUsuario.PACIENTE: frozenset(),
}


class Usuario(Base):
    __tablename__ = "usuarios"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    nome: Mapped[str] = mapped_column(String(150), nullable=False)
    email: Mapped[str] = mapped_column(String(150), unique=True, index=True, nullable=False)
    senha_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    papel: Mapped[PapelUsuario] = mapped_column(
        Enum(
            PapelUsuario,
            name="papelusuario",
            native_enum=False,
            create_constraint=True,
            length=20,
            values_callable=lambda papeis: [papel.value for papel in papeis],
        ),
        nullable=False,
        default=PapelUsuario.PACIENTE,
    )
    data_criacao: Mapped[str] = mapped_column(
        String(30),
        nullable=False,
        default=lambda: datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
    )

    paciente: Mapped["Paciente | None"] = relationship(back_populates="usuario")
