from __future__ import annotations

from sqlalchemy import String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base


class Medico(Base):
    __tablename__ = "medicos"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    nome: Mapped[str] = mapped_column(String(150), nullable=False)
    crm: Mapped[str] = mapped_column(String(30), unique=True, nullable=False)
    especialidade: Mapped[str] = mapped_column(String(100), nullable=False)

    horarios: Mapped[list["Horario"]] = relationship(back_populates="medico")
    consultas: Mapped[list["Consulta"]] = relationship(back_populates="medico")
