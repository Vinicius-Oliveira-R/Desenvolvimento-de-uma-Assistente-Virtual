from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.backend.core.database import Base


class Usuario(Base):
    __tablename__ = "usuarios"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    nome: Mapped[str] = mapped_column(String(150), nullable=False)
    email: Mapped[str] = mapped_column(String(150), unique=True, index=True, nullable=False)
    senha_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    tipo: Mapped[str] = mapped_column(String(50), nullable=False, default="paciente")
    data_criacao: Mapped[str] = mapped_column(
        String(30),
        nullable=False,
        default=lambda: datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
    )

    paciente: Mapped["Paciente | None"] = relationship(back_populates="usuario")
