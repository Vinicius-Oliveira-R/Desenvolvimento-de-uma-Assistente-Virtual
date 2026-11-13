from collections.abc import Iterator
from datetime import date, datetime, timedelta

from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.backend.core.exceptions import BusinessRuleError, ConflictError, NotFoundError
from app.backend.models import Horario, Medico, Usuario
from app.backend.repositories.horario_repository import HorarioRepository
from app.backend.schemas.horario import HorarioCreate, HorarioOut, LiberacaoDeHorarios, ResultadoDaLiberacao


class HorarioService:
    def __init__(self, db: Session):
        self.repository, self.db = HorarioRepository(db), db

    def _bloquear_medico(self, medico_id: int) -> None:
        # Todos os geradores da agenda serializam no mesmo profissional.
        self.db.execute(update(Medico).where(Medico.id == medico_id).values(ativo=Medico.ativo))
        medico = self.db.execute(select(Medico).where(Medico.id == medico_id).with_for_update()).scalar_one_or_none()
        if medico is None:
            raise NotFoundError("Médico não encontrado")
        if not medico.ativo or (medico.usuario_id and not self.db.get(Usuario, medico.usuario_id).ativo):
            raise BusinessRuleError("Médico inativo não pode receber novos horários")

    def _verificar_intersecoes(self, medico_id: int, pedidos: list[tuple[str, str, str]], repetir: bool) -> list[Horario]:
        inicio, fim = min(p[0] for p in pedidos), max(p[0] for p in pedidos)
        existentes = self.db.query(Horario).filter(Horario.medico_id == medico_id, Horario.data >= inicio, Horario.data <= fim).all()
        novos = []
        for dia, hora_inicio, hora_fim in pedidos:
            conflitantes = [h for h in [*existentes, *novos] if h.data == dia and h.hora_inicio < hora_fim and h.hora_fim > hora_inicio]
            if conflitantes:
                if repetir and len(conflitantes) == 1 and conflitantes[0].hora_inicio == hora_inicio and conflitantes[0].hora_fim == hora_fim:
                    continue  # Nunca torna uma vaga já ocupada disponível novamente.
                raise ConflictError("Existe horário sobreposto nesse período; nenhum horário do pedido foi gravado")
            novos.append(Horario(medico_id=medico_id, data=dia, hora_inicio=hora_inicio, hora_fim=hora_fim, disponivel=True))
        return novos

    def _gravar(self, medico_id: int, pedidos: list[tuple[str, str, str]], repetir: bool) -> list[Horario]:
        if not pedidos:
            return []
        try:
            self._bloquear_medico(medico_id)
            novos = self._verificar_intersecoes(medico_id, pedidos, repetir)
            self.db.add_all(novos)
            self.db.commit()
            return novos
        except IntegrityError as exc:
            self.db.rollback()
            raise ConflictError("A agenda foi modificada; há conflito entre horários") from exc
        except Exception:
            self.db.rollback()
            raise

    def create(self, payload: HorarioCreate) -> HorarioOut:
        novos = self._gravar(payload.medico_id, [(payload.data, payload.hora_inicio, payload.hora_fim)], False)
        return HorarioOut.model_validate(novos[0])

    def liberar(self, pedido: LiberacaoDeHorarios, hoje: date) -> ResultadoDaLiberacao:
        if pedido.data_inicio < hoje:
            raise BusinessRuleError("Não é possível liberar horários em datas passadas")
        pedidos = [(dia.isoformat(), inicio, fim)
                   for dia in _dias(pedido.data_inicio, pedido.data_fim, pedido.dias_semana)
                   for inicio, fim in _faixas(pedido.hora_inicio, pedido.hora_fim, pedido.duracao_minutos)]
        novos = self._gravar(pedido.medico_id, pedidos, True)
        return ResultadoDaLiberacao(criados=len(novos), ja_existentes=len(pedidos) - len(novos))

    def list(self, *, medico_id: int | None = None, data: str | None = None, disponivel: bool | None = None) -> list[HorarioOut]:
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
