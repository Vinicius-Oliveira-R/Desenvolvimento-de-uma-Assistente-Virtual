from __future__ import annotations

from sqlalchemy import String, ForeignKey
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.backend.core.database import Base


class Paciente(Base):
    __tablename__ = "pacientes"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    usuario_id: Mapped[int] = mapped_column(ForeignKey("usuarios.id"), unique=True, nullable=False)
    nome: Mapped[str] = mapped_column(String(150), nullable=False)
    cpf: Mapped[str] = mapped_column(String(11), unique=True, nullable=False)
    data_nascimento: Mapped[str] = mapped_column(String(30), nullable=False)
    telefone: Mapped[str] = mapped_column(String(20), nullable=False)

    usuario: Mapped["Usuario"] = relationship(back_populates="paciente")
    consultas: Mapped[list["Consulta"]] = relationship(back_populates="paciente")
