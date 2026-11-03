from sqlalchemy.orm import Query, Session

from app.backend.models import Consulta, Horario, Medico, StatusConsulta

ConsultaDetalhada = tuple[Consulta, Horario, Medico]


class ConsultaRepository:
    def __init__(self, db: Session):
        self.db = db

    def add(self, consulta: Consulta) -> Consulta:
        self.db.add(consulta)
        self.db.flush()
        return consulta

    def list_all(self) -> list[Consulta]:
        return self.db.query(Consulta).all()

    def get_by_id(self, consulta_id: int) -> Consulta | None:
        return self.db.query(Consulta).filter(Consulta.id == consulta_id).first()

    def get_by_id_for_update(self, consulta_id: int) -> Consulta | None:
        return (
            self.db.query(Consulta)
            .filter(Consulta.id == consulta_id)
            .with_for_update()
            .populate_existing()
            .first()
        )

    def get_ativa_por_horario(self, horario_id: int) -> Consulta | None:
        return (
            self.db.query(Consulta)
            .filter(Consulta.horario_id == horario_id, Consulta.status != StatusConsulta.CANCELADA)
            .first()
        )

    def get_detalhada(self, consulta_id: int) -> ConsultaDetalhada | None:
        row = self._query_detalhada().filter(Consulta.id == consulta_id).first()
        return (row[0], row[1], row[2]) if row else None

    def list_detalhadas_by_paciente(
        self,
        paciente_id: int,
        *,
        desde_data: str | None = None,
        apenas_agendadas: bool = False,
    ) -> list[ConsultaDetalhada]:
        query = self._query_detalhada().filter(Consulta.paciente_id == paciente_id)
        if desde_data:
            query = query.filter(Horario.data >= desde_data)
        if apenas_agendadas:
            query = query.filter(Consulta.status == StatusConsulta.AGENDADA)
        rows = query.order_by(Horario.data, Horario.hora_inicio).all()
        return [(consulta, horario, medico) for consulta, horario, medico in rows]

    def _query_detalhada(self) -> Query:
        return (
            self.db.query(Consulta, Horario, Medico)
            .join(Horario, Consulta.horario_id == Horario.id)
            .join(Medico, Consulta.medico_id == Medico.id)
        )
