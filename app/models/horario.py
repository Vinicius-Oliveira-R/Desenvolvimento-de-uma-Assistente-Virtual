from __future__ import annotations

from sqlalchemy import Boolean, String, ForeignKey, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base


class Horario(Base):
    __tablename__ = "horarios"
    __table_args__ = (
        UniqueConstraint("medico_id", "data", "hora_inicio", name="uq_horario_medico_data_inicio"),
    )

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    medico_id: Mapped[int] = mapped_column(ForeignKey("medicos.id"), nullable=False)
    data: Mapped[str] = mapped_column(String(30), nullable=False)
    hora_inicio: Mapped[str] = mapped_column(String(5), nullable=False)
    hora_fim: Mapped[str] = mapped_column(String(5), nullable=False)
    disponivel: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    medico: Mapped["Medico"] = relationship(back_populates="horarios")
    consultas: Mapped[list["Consulta"]] = relationship(back_populates="horario")
