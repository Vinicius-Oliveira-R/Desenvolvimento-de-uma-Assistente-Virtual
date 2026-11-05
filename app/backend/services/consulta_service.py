from collections.abc import Iterator
from contextlib import contextmanager
from datetime import datetime, timezone

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.backend.core.exceptions import BusinessRuleError, ConflictError, HorarioIndisponivelError, NotFoundError
from app.backend.models import Consulta, Horario, Medico, Paciente, StatusConsulta
from app.backend.repositories.consulta_repository import ConsultaRepository, FiltroAgenda
from app.backend.repositories.horario_repository import HorarioRepository
from app.backend.repositories.paciente_repository import PacienteRepository
from app.backend.schemas.consulta import (
    ConfirmacaoConsulta,
    ConsultaAgendaOut,
    ConsultaCreate,
    ConsultaDetalhadaOut,
    ConsultaOut,
    ConsultaUpdate,
)


class ConsultaService:
    def __init__(self, db: Session):
        self.db = db
        self.repository = ConsultaRepository(db)
        self.horarios = HorarioRepository(db)

    @staticmethod
    def _utc_now() -> str:
        return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    def create(self, payload: ConsultaCreate) -> ConsultaOut:
        with self._transacao():
            self._garantir_existencia(Paciente, payload.paciente_id, "Paciente não encontrado")
            self._garantir_existencia(Medico, payload.medico_id, "Médico não encontrado")
            horario = self._bloquear_horario(payload.horario_id)
            if horario.medico_id != payload.medico_id:
                raise BusinessRuleError("O horário informado não pertence ao médico selecionado.")
            if horario.data != payload.data:
                raise BusinessRuleError("A data informada não corresponde ao horário selecionado.")
            self._ocupar(horario, payload.paciente_id)
            agora = self._utc_now()
            consulta = self.repository.add(
                Consulta(
                    paciente_id=payload.paciente_id,
                    medico_id=payload.medico_id,
                    horario_id=horario.id,
                    data=horario.data,
                    status=StatusConsulta.AGENDADA,
                    observacao=payload.observacao,
                    data_criacao=agora,
                    data_atualizacao=agora,
                )
            )
        return ConsultaOut.model_validate(consulta)

    def list_agenda(self, filtro: FiltroAgenda) -> list[ConsultaAgendaOut]:
        return [ConsultaAgendaOut.from_agenda(*linha) for linha in self.repository.list_agenda(filtro)]

    def list_by_usuario(self, usuario_id: int) -> list[ConsultaDetalhadaOut]:
        paciente = PacienteRepository(self.db).get_by_usuario_id(usuario_id)
        if paciente is None:
            raise NotFoundError("Nenhum paciente vinculado ao usuário autenticado")
        return [
            ConsultaDetalhadaOut.from_models(consulta, horario, medico)
            for consulta, horario, medico in self.repository.list_detalhadas_by_paciente(paciente.id)
        ]

    def get_da_agenda(self, consulta_id: int) -> ConsultaAgendaOut:
        linha = self.repository.get_da_agenda(consulta_id)
        if linha is None:
            raise NotFoundError("Consulta não encontrada")
        return ConsultaAgendaOut.from_agenda(*linha)

    def update(self, consulta_id: int, payload: ConsultaUpdate) -> ConsultaOut:
        with self._transacao():
            consulta = self._bloquear_consulta(consulta_id)
            alteracoes = payload.model_dump(exclude={"confirmado"}, exclude_none=True)
            if alteracoes and not payload.confirmado:
                raise BusinessRuleError("A alteração da consulta exige confirmação explícita do paciente.")
            if alteracoes and consulta.status == StatusConsulta.CANCELADA:
                raise ConflictError("Consulta cancelada não pode ser alterada.")

            if payload.horario_id is not None and payload.horario_id != consulta.horario_id:
                self._transferir(consulta, payload.horario_id)
            if (payload.medico_id is not None and payload.medico_id != consulta.medico_id) or (
                payload.data is not None and payload.data != consulta.data
            ):
                raise BusinessRuleError("Para alterar médico ou data, informe um novo horário.")

            if payload.status == StatusConsulta.CANCELADA:
                self._liberar(consulta)
            elif payload.status is not None:
                consulta.status = payload.status
            if payload.observacao is not None:
                consulta.observacao = payload.observacao
            consulta.data_atualizacao = self._utc_now()
        return ConsultaOut.model_validate(consulta)

    def cancel(self, consulta_id: int, payload: ConfirmacaoConsulta) -> ConsultaOut:
        with self._transacao():
            consulta = self._bloquear_consulta(consulta_id)
            if consulta.status == StatusConsulta.CANCELADA:
                raise ConflictError("Consulta já cancelada")
            if not payload.confirmado:
                raise BusinessRuleError("O cancelamento da consulta exige confirmação explícita.")
            self._liberar(consulta)
        return ConsultaOut.model_validate(consulta)

    @contextmanager
    def _transacao(self) -> Iterator[None]:
        try:
            yield
            self.db.commit()
        except IntegrityError as exc:
            self.db.rollback()
            raise HorarioIndisponivelError() from exc
        except Exception:
            self.db.rollback()
            raise

    def _garantir_existencia(self, modelo: type[Paciente] | type[Medico], identificador: int, mensagem: str) -> None:
        if self.db.get(modelo, identificador) is None:
            raise NotFoundError(mensagem)

    def _bloquear_horario(self, horario_id: int) -> Horario:
        horario = self.horarios.get_by_id_for_update(horario_id)
        if horario is None:
            raise NotFoundError("Horário não encontrado")
        return horario

    def _bloquear_consulta(self, consulta_id: int) -> Consulta:
        consulta = self.repository.get_by_id_for_update(consulta_id)
        if consulta is None:
            raise NotFoundError("Consulta não encontrada")
        return consulta

    def _ocupar(self, horario: Horario, paciente_id: int) -> None:
        ocupante = self.repository.get_ativa_por_horario(horario.id)
        if ocupante and ocupante.paciente_id == paciente_id:
            raise ConflictError("Você já possui uma consulta agendada neste horário.")
        if ocupante or not horario.disponivel:
            raise HorarioIndisponivelError()
        horario.disponivel = False

    def _liberar(self, consulta: Consulta) -> None:
        horario = self.horarios.get_by_id_for_update(consulta.horario_id)
        if horario:
            horario.disponivel = True
        consulta.status = StatusConsulta.CANCELADA
        consulta.data_atualizacao = self._utc_now()

    def _transferir(self, consulta: Consulta, novo_horario_id: int) -> None:
        bloqueados = {h.id: h for h in self.horarios.list_for_update([consulta.horario_id, novo_horario_id])}
        novo = bloqueados.get(novo_horario_id)
        if novo is None:
            raise NotFoundError("Horário não encontrado")
        self._ocupar(novo, consulta.paciente_id)
        antigo = bloqueados.get(consulta.horario_id)
        if antigo:
            antigo.disponivel = True
        consulta.horario_id = novo.id
        consulta.medico_id = novo.medico_id
        consulta.data = novo.data
