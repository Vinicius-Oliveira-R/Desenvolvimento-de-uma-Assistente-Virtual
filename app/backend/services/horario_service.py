from collections.abc import Iterator
from datetime import date, datetime, timedelta

from sqlalchemy.orm import Session

from app.backend.core.exceptions import BusinessRuleError, NotFoundError
from app.backend.models import Horario, Medico
from app.backend.repositories.horario_repository import HorarioRepository
from app.backend.schemas.horario import HorarioCreate, HorarioOut, LiberacaoDeHorarios, ResultadoDaLiberacao


class HorarioService:
    def __init__(self, db: Session):
        self.repository = HorarioRepository(db)
        self.db = db

    def create(self, payload: HorarioCreate) -> HorarioOut:
        medico = self.db.query(Medico).filter(Medico.id == payload.medico_id).first()
        if not medico:
            raise NotFoundError("Médico não encontrado")

        horario = Horario(
            medico_id=payload.medico_id,
            data=payload.data,
            hora_inicio=payload.hora_inicio,
            hora_fim=payload.hora_fim,
            disponivel=True,
        )
        saved = self.repository.create(horario)
        return HorarioOut.model_validate(saved)

    def liberar(self, pedido: LiberacaoDeHorarios, hoje: date) -> ResultadoDaLiberacao:
        if self.db.get(Medico, pedido.medico_id) is None:
            raise NotFoundError("Médico não encontrado")
        if pedido.data_inicio < hoje:
            raise BusinessRuleError("Não é possível liberar horários em datas passadas")

        existentes = self.repository.chaves_no_periodo(
            pedido.medico_id, pedido.data_inicio.isoformat(), pedido.data_fim.isoformat()
        )
        pedidos = [
            (dia.isoformat(), inicio, fim)
            for dia in _dias(pedido.data_inicio, pedido.data_fim, pedido.dias_semana)
            for inicio, fim in _faixas(pedido.hora_inicio, pedido.hora_fim, pedido.duracao_minutos)
        ]
        novos = [
            Horario(medico_id=pedido.medico_id, data=dia, hora_inicio=inicio, hora_fim=fim, disponivel=True)
            for dia, inicio, fim in pedidos
            if (dia, inicio) not in existentes
        ]
        self.repository.add_all(novos)
        return ResultadoDaLiberacao(criados=len(novos), ja_existentes=len(pedidos) - len(novos))

    def list(
        self, *, medico_id: int | None = None, data: str | None = None, disponivel: bool | None = None
    ) -> list[HorarioOut]:
        horarios = self.repository.list_filtered(medico_id=medico_id, data=data, disponivel=disponivel)
        return [HorarioOut.model_validate(item) for item in horarios]


def _dias(inicio: date, fim: date, dias_semana: list[int]) -> Iterator[date]:
    for deslocamento in range((fim - inicio).days + 1):
        dia = inicio + timedelta(days=deslocamento)
        if dia.weekday() in dias_semana:
            yield dia


def _faixas(hora_inicio: str, hora_fim: str, duracao_minutos: int) -> Iterator[tuple[str, str]]:
    inicio, limite = (datetime.strptime(hora, "%H:%M") for hora in (hora_inicio, hora_fim))
    duracao = timedelta(minutes=duracao_minutos)
    while inicio + duracao <= limite:
        yield inicio.strftime("%H:%M"), (inicio + duracao).strftime("%H:%M")
        inicio += duracao
