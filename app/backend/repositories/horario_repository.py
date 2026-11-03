from collections.abc import Sequence
from dataclasses import dataclass

from sqlalchemy import and_, or_
from sqlalchemy.orm import Session

from app.backend.models import Horario


@dataclass(frozen=True)
class FiltroHorarios:
    medico_ids: Sequence[int]
    apos_data: str
    apos_hora: str = ""
    ate_data: str | None = None
    faixa_horaria: tuple[str, str] | None = None
    hora_exata: str | None = None
    excluir_ids: Sequence[int] = ()


class HorarioRepository:
    def __init__(self, db: Session):
        self.db = db

    def create(self, horario: Horario) -> Horario:
        self.db.add(horario)
        self.db.commit()
        self.db.refresh(horario)
        return horario

    def list_all(self) -> list[Horario]:
        return self.db.query(Horario).all()

    def get_by_id(self, horario_id: int) -> Horario | None:
        return self.db.query(Horario).filter(Horario.id == horario_id).first()

    def get_by_id_for_update(self, horario_id: int) -> Horario | None:
        return (
            self.db.query(Horario)
            .filter(Horario.id == horario_id)
            .with_for_update()
            .populate_existing()
            .first()
        )

    def list_for_update(self, horario_ids: Sequence[int]) -> list[Horario]:
        return (
            self.db.query(Horario)
            .filter(Horario.id.in_(horario_ids))
            .order_by(Horario.id)
            .with_for_update()
            .populate_existing()
            .all()
        )

    def find_slot(self, medico_id: int, data: str, hora_inicio: str) -> Horario | None:
        return (
            self.db.query(Horario)
            .filter(Horario.medico_id == medico_id, Horario.data == data, Horario.hora_inicio == hora_inicio)
            .first()
        )

    def search_available(self, filtro: FiltroHorarios, limite: int = 1) -> list[Horario]:
        query = self.db.query(Horario).filter(
            Horario.disponivel.is_(True),
            Horario.medico_id.in_(filtro.medico_ids),
            or_(
                Horario.data > filtro.apos_data,
                and_(Horario.data == filtro.apos_data, Horario.hora_inicio > filtro.apos_hora),
            ),
        )
        if filtro.ate_data:
            query = query.filter(Horario.data <= filtro.ate_data)
        if filtro.faixa_horaria:
            inicio, fim = filtro.faixa_horaria
            query = query.filter(Horario.hora_inicio >= inicio, Horario.hora_inicio < fim)
        if filtro.hora_exata:
            query = query.filter(Horario.hora_inicio == filtro.hora_exata)
        if filtro.excluir_ids:
            query = query.filter(Horario.id.notin_(filtro.excluir_ids))
        return query.order_by(Horario.data, Horario.hora_inicio, Horario.id).limit(limite).all()
