from __future__ import annotations

from sqlalchemy import ForeignKey, Index, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.backend.core.database import Base


class Medico(Base):
    __tablename__ = "medicos"
    __table_args__ = (Index("uq_medicos_usuario_id", "usuario_id", unique=True),)

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    nome: Mapped[str] = mapped_column(String(150), nullable=False)
    crm: Mapped[str] = mapped_column(String(30), unique=True, nullable=False)
    especialidade: Mapped[str] = mapped_column(String(100), nullable=False)
    usuario_id: Mapped[int | None] = mapped_column(ForeignKey("usuarios.id"), nullable=True)

    usuario: Mapped["Usuario | None"] = relationship(back_populates="medico")
    horarios: Mapped[list["Horario"]] = relationship(back_populates="medico")
    consultas: Mapped[list["Consulta"]] = relationship(back_populates="medico")
