from dataclasses import dataclass

from sqlalchemy.orm import Query, Session

from app.backend.models import Consulta, Horario, Medico, Paciente, StatusConsulta

ConsultaDetalhada = tuple[Consulta, Horario, Medico]
ConsultaDaAgenda = tuple[Consulta, Horario, Medico, Paciente]


@dataclass(frozen=True)
class FiltroAgenda:
    data_inicio: str | None = None
    data_fim: str | None = None
    medico_id: int | None = None
    status: StatusConsulta | None = None


class ConsultaRepository:
    def __init__(self, db: Session):
        self.db = db

    def add(self, consulta: Consulta) -> Consulta:
        self.db.add(consulta)
        self.db.flush()
        return consulta

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

    def get_da_agenda(self, consulta_id: int) -> ConsultaDaAgenda | None:
        row = self._query_agenda().filter(Consulta.id == consulta_id).first()
        return (row[0], row[1], row[2], row[3]) if row else None

    def list_agenda(self, filtro: FiltroAgenda) -> list[ConsultaDaAgenda]:
        query = self._query_agenda()
        if filtro.data_inicio:
            query = query.filter(Horario.data >= filtro.data_inicio)
        if filtro.data_fim:
            query = query.filter(Horario.data <= filtro.data_fim)
        if filtro.medico_id:
            query = query.filter(Consulta.medico_id == filtro.medico_id)
        if filtro.status:
            query = query.filter(Consulta.status == filtro.status)
        rows = query.order_by(Horario.data, Horario.hora_inicio, Consulta.id).all()
        return [(consulta, horario, medico, paciente) for consulta, horario, medico, paciente in rows]

    def _query_agenda(self) -> Query:
        return self._query_detalhada().add_entity(Paciente).join(Paciente, Consulta.paciente_id == Paciente.id)

    def _query_detalhada(self) -> Query:
        return (
            self.db.query(Consulta, Horario, Medico)
            .join(Horario, Consulta.horario_id == Horario.id)
            .join(Medico, Consulta.medico_id == Medico.id)
        )
