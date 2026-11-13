from __future__ import annotations

from sqlalchemy import Boolean, String, ForeignKey, UniqueConstraint, CheckConstraint, event, DDL, text
from sqlalchemy.dialects.postgresql import ExcludeConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.backend.core.database import Base


class Horario(Base):
    __tablename__ = "horarios"
    __table_args__ = (
        UniqueConstraint("medico_id", "data", "hora_inicio", name="uq_horario_medico_data_inicio"),
        CheckConstraint("hora_fim > hora_inicio", name="ck_horario_intervalo"),
        ExcludeConstraint(
            ("medico_id", "="), ("data", "="),
            (text("int4range((substring(hora_inicio,1,2)::int * 60 + substring(hora_inicio,4,2)::int), (substring(hora_fim,1,2)::int * 60 + substring(hora_fim,4,2)::int), '[)')"), "&&"),
            using="gist", name="ex_horario_sem_sobreposicao",
        ).ddl_if(dialect="postgresql"),
    )

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    medico_id: Mapped[int] = mapped_column(ForeignKey("medicos.id"), nullable=False)
    data: Mapped[str] = mapped_column(String(30), nullable=False)
    hora_inicio: Mapped[str] = mapped_column(String(5), nullable=False)
    hora_fim: Mapped[str] = mapped_column(String(5), nullable=False)
    disponivel: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    medico: Mapped["Medico"] = relationship(back_populates="horarios")
    consultas: Mapped[list["Consulta"]] = relationship(back_populates="horario")


# Extensão necessária à igualdade de inteiros/texto na exclusion constraint.
event.listen(Base.metadata, "before_create", DDL("CREATE EXTENSION IF NOT EXISTS btree_gist").execute_if(dialect="postgresql"))

SQLITE_OVERLAP_TRIGGERS = (
    """CREATE TRIGGER IF NOT EXISTS horarios_overlap_insert BEFORE INSERT ON horarios
    WHEN EXISTS (SELECT 1 FROM horarios h WHERE h.medico_id=NEW.medico_id AND h.data=NEW.data
        AND h.hora_inicio < NEW.hora_fim AND h.hora_fim > NEW.hora_inicio)
    BEGIN SELECT RAISE(ABORT, 'horarios_overlap'); END""",
    """CREATE TRIGGER IF NOT EXISTS horarios_overlap_update BEFORE UPDATE ON horarios
    WHEN EXISTS (SELECT 1 FROM horarios h WHERE h.id<>NEW.id AND h.medico_id=NEW.medico_id AND h.data=NEW.data
        AND h.hora_inicio < NEW.hora_fim AND h.hora_fim > NEW.hora_inicio)
    BEGIN SELECT RAISE(ABORT, 'horarios_overlap'); END""",
)
for _trigger in SQLITE_OVERLAP_TRIGGERS:
    event.listen(Horario.__table__, "after_create", DDL(_trigger).execute_if(dialect="sqlite"))
