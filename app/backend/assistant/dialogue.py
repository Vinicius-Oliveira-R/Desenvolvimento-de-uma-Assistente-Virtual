from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date
from enum import StrEnum

from sqlalchemy.orm import Session

from app.backend.assistant.especialidades import ESPECIALIDADE_PADRAO, buscar_especialidade
from app.backend.assistant.nlp import (
    INTENCOES_DE_RESPOSTA,
    INTENCOES_SOCIAIS,
    Entidades,
    Intencao,
    MensagemInterpretada,
)
from app.backend.assistant.temporal import IntervaloDatas
from app.backend.core.clock import Clock
from app.backend.core.exceptions import DomainError, HorarioIndisponivelError
from app.backend.core.text import normalizar
from app.backend.models import Horario, Medico, Paciente, Usuario
from app.backend.models.notificacao import Notificacao, TipoNotificacao
from app.backend.repositories.consulta_repository import ConsultaRepository
from app.backend.repositories.notificacao_repository import NotificacaoRepository
from app.backend.schemas.assistant import AcaoPendente, CriteriosAgendamento, TipoAcao
from app.backend.schemas.consulta import ConfirmacaoConsulta, ConsultaCreate, ConsultaDetalhadaOut
from app.backend.services.agenda_service import AgendaService
from app.backend.services.consulta_service import ConsultaService
from app.backend.services.notificacao_service import NotificacaoService


class TipoResultado(StrEnum):
    CONSULTA_AGENDADA = "consulta_agendada"
    SUGESTAO_HORARIO = "sugestao_horario"
    HORARIO_RESERVADO = "horario_reservado"
    SEM_HORARIOS = "sem_horarios"
    MEDICO_NAO_ENCONTRADO = "medico_nao_encontrado"
    MEDICO_AMBIGUO = "medico_ambiguo"
    FALTA_ESPECIALIDADE = "falta_especialidade"
    CONFIRMAR_CANCELAMENTO = "confirmar_cancelamento"
    CONSULTA_CANCELADA = "consulta_cancelada"
    CONSULTA_NAO_ENCONTRADA = "consulta_nao_encontrada"
    CANCELAMENTO_AMBIGUO = "cancelamento_ambiguo"
    LISTA_CONSULTAS = "lista_consultas"
    SEM_CONSULTAS = "sem_consultas"
    AGENDAMENTO_DESCARTADO = "agendamento_descartado"
    CANCELAMENTO_DESCARTADO = "cancelamento_descartado"
    ORIENTAR_REMARCACAO = "orientar_remarcacao"
    REGRA_VIOLADA = "regra_violada"
    ORIENTACAO_MEDICA_BLOQUEADA = "orientacao_medica_bloqueada"
    SAUDACAO = "saudacao"
    AGRADECIMENTO = "agradecimento"
    AJUDA = "ajuda"
    PACIENTE_NAO_CADASTRADO = "paciente_nao_cadastrado"
    SOLICITACAO_REMARCACAO = "solicitacao_remarcacao"
    SOLICITACAO_CANCELAMENTO = "solicitacao_cancelamento"
    REMARCACAO_ACEITA = "remarcacao_aceita"
    CANCELAMENTO_ACEITO = "cancelamento_aceito"
    SOLICITACAO_RECUSADA = "solicitacao_recusada"


class Aviso(StrEnum):
    HORARIO_RESERVADO = "horario_reservado"
    HORARIO_PEDIDO_INDISPONIVEL = "horario_pedido_indisponivel"


@dataclass(frozen=True)
class OpcaoAgenda:
    horario_id: int
    medico: str
    especialidade: str
    data: date
    hora: str
    consulta_id: int | None = None

    @classmethod
    def from_horario(cls, horario: Horario, medico: Medico) -> "OpcaoAgenda":
        return cls(horario.id, medico.nome, medico.especialidade, date.fromisoformat(horario.data), horario.hora_inicio)

    @classmethod
    def from_consulta(cls, consulta: ConsultaDetalhadaOut, horario_id: int) -> "OpcaoAgenda":
        return cls(
            horario_id,
            consulta.medico_nome,
            consulta.especialidade,
            date.fromisoformat(consulta.data),
            consulta.hora_inicio,
            consulta.id,
        )


@dataclass(frozen=True)
class ResultadoDialogo:
    tipo: TipoResultado
    opcao: OpcaoAgenda | None = None
    opcao_nova: OpcaoAgenda | None = None
    opcoes: tuple[OpcaoAgenda, ...] = ()
    aviso: Aviso | None = None
    especialidade: str | None = None
    periodo: IntervaloDatas | None = None
    medicos: tuple[str, ...] = ()
    detalhe: str | None = None
    acao_pendente: AcaoPendente | None = None
    consulta: ConsultaDetalhadaOut | None = None


INTENCAO_DA_ACAO = {TipoAcao.AGENDAR: Intencao.AGENDAR, TipoAcao.CANCELAR: Intencao.CANCELAR}
APRESENTACOES_DE_SOLICITACAO = (TipoResultado.SOLICITACAO_REMARCACAO, TipoResultado.SOLICITACAO_CANCELAMENTO)


def criterios_de(entidades: Entidades) -> CriteriosAgendamento:
    inicio, fim = (entidades.data, entidades.data) if entidades.data else (None, None)
    if entidades.periodo and not entidades.data:
        inicio, fim = entidades.periodo.inicio, entidades.periodo.fim
    return CriteriosAgendamento(
        medico_nome=entidades.medico,
        especialidade=entidades.especialidade,
        data_inicio=inicio,
        data_fim=fim,
        hora=entidades.hora,
        turno=entidades.turno,
    )


def _periodo_de(criterios: CriteriosAgendamento) -> IntervaloDatas | None:
    if criterios.data_inicio is None:
        return None
    return IntervaloDatas(criterios.data_inicio, criterios.data_fim or criterios.data_inicio)


def _com_especialidade_padrao(criterios: CriteriosAgendamento) -> CriteriosAgendamento:
    return criterios.model_copy(update={"especialidade": ESPECIALIDADE_PADRAO})


class DialogueManager:
    OBSERVACAO_AGENDAMENTO = "Agendamento realizado pelo assistente virtual"

    def __init__(self, db: Session, clock: Clock):
        self.clock = clock
        self.agenda = AgendaService(db, clock)
        self.consultas = ConsultaService(db)
        self.consultas_repository = ConsultaRepository(db)
        self.notificacoes = NotificacaoService(db)
        self.db = db

    def handle(
        self,
        mensagem: MensagemInterpretada,
        paciente: Paciente,
        pendente: AcaoPendente | None,
        solicitacoes_vistas: Sequence[int] = (),
    ) -> ResultadoDialogo:
        if pendente and (continuacao := self._continuar(mensagem, paciente, pendente)):
            return continuacao
        if pendente is None and (pedido := self._apresentar_solicitacao(paciente, solicitacoes_vistas)):
            return pedido
        return self._rotear(mensagem, paciente)

    def _continuar(
        self, mensagem: MensagemInterpretada, paciente: Paciente, pendente: AcaoPendente
    ) -> ResultadoDialogo | None:
        if pendente.tipo == TipoAcao.RESPONDER_SOLICITACAO:
            if mensagem.negativa or mensagem.afirmativa:
                return self._responder_solicitacao(paciente, pendente.notificacao_id, not mensagem.negativa)
            return None
        sem_criterios = not mensagem.entidades.possui_criterios
        neutras = (Intencao.DESCONHECIDA, *INTENCOES_DE_RESPOSTA, *INTENCOES_SOCIAIS)
        compativel = mensagem.intencao in (*neutras, INTENCAO_DA_ACAO[pendente.tipo])
        agendando = pendente.tipo == TipoAcao.AGENDAR

        if agendando and not pendente.criterios.possui_alvo:
            respondeu = compativel and mensagem.intencao not in INTENCOES_SOCIAIS
            return self._definir_especialidade(mensagem, paciente, pendente.criterios) if respondeu else None
        if agendando and mensagem.pede_outra_opcao and sem_criterios:
            recusados = [*pendente.recusados, *([pendente.horario_id] if pendente.horario_id else [])]
            return self._agendar(paciente, pendente.criterios, recusados)
        if compativel and sem_criterios and mensagem.negativa:
            return ResultadoDialogo(
                TipoResultado.AGENDAMENTO_DESCARTADO if agendando else TipoResultado.CANCELAMENTO_DESCARTADO
            )
        if compativel and sem_criterios and mensagem.afirmativa:
            return self._executar(pendente, paciente)
        if agendando and mensagem.intencao in (Intencao.AGENDAR, *neutras) and not sem_criterios:
            return self._agendar(paciente, pendente.criterios.merge(criterios_de(mensagem.entidades)))
        return None

    def _definir_especialidade(
        self, mensagem: MensagemInterpretada, paciente: Paciente, pendentes: CriteriosAgendamento
    ) -> ResultadoDialogo:
        criterios = pendentes.merge(criterios_de(mensagem.entidades))
        if criterios.possui_alvo:
            return self._agendar(paciente, criterios)
        if mensagem.negativa and not (mensagem.sem_preferencia or mensagem.entidades.possui_criterios):
            return ResultadoDialogo(TipoResultado.AGENDAMENTO_DESCARTADO)
        # A especialidade é perguntada uma só vez: dúvida, "sim" ou resposta não reconhecida seguem com o padrão.
        return self._agendar(paciente, _com_especialidade_padrao(criterios))

    def _rotear(self, mensagem: MensagemInterpretada, paciente: Paciente) -> ResultadoDialogo:
        match mensagem.intencao:
            case Intencao.AGENDAR:
                criterios = criterios_de(mensagem.entidades)
                if mensagem.sem_preferencia and not criterios.possui_alvo:
                    criterios = _com_especialidade_padrao(criterios)
                return self._agendar(paciente, criterios)
            case Intencao.CANCELAR:
                return self._solicitar_cancelamento(paciente, mensagem.entidades)
            case Intencao.REMARCAR:
                return ResultadoDialogo(TipoResultado.ORIENTAR_REMARCACAO)
            case Intencao.ORIENTACAO_MEDICA:
                return self._recusar_orientacao_medica()
            case Intencao.LISTAR:
                return self._listar(paciente)
            case Intencao.SAUDACAO:
                return ResultadoDialogo(TipoResultado.SAUDACAO)
            case Intencao.AGRADECIMENTO:
                return ResultadoDialogo(TipoResultado.AGRADECIMENTO)
            case _:
                return ResultadoDialogo(TipoResultado.AJUDA)

    @staticmethod
    def _recusar_orientacao_medica() -> ResultadoDialogo:
        # O sistema não diagnostica nem indica medicamentos: o pedido é recusado e vira oferta de consulta.
        consulta_com_clinico = AcaoPendente(
            tipo=TipoAcao.AGENDAR, criterios=CriteriosAgendamento(especialidade=ESPECIALIDADE_PADRAO)
        )
        return ResultadoDialogo(TipoResultado.ORIENTACAO_MEDICA_BLOQUEADA, acao_pendente=consulta_com_clinico)

    def _agendar(
        self, paciente: Paciente, criterios: CriteriosAgendamento, recusados: Sequence[int] = ()
    ) -> ResultadoDialogo:
        medicos, falha = self._resolver_medicos(criterios)
        if falha:
            return falha
        pedido_exato = (
            len(medicos) == 1 and criterios.hora and criterios.data_inicio and criterios.data_inicio == criterios.data_fim
        )
        if pedido_exato and not recusados:
            horario = self.agenda.find_slot(medicos[0].id, criterios.data_inicio, criterios.hora)
            if horario and horario.disponivel and self.agenda.is_future(horario):
                return self._reservar(horario, paciente, criterios)
            return self._sugerir(medicos, criterios.without_time(), recusados, Aviso.HORARIO_PEDIDO_INDISPONIVEL)
        return self._sugerir(medicos, criterios, recusados)

    def _sugerir(
        self,
        medicos: Sequence[Medico],
        criterios: CriteriosAgendamento,
        recusados: Sequence[int],
        aviso: Aviso | None = None,
    ) -> ResultadoDialogo:
        horarios = self._buscar(medicos, criterios, recusados)
        if not horarios and criterios.hora:
            criterios, aviso = criterios.without_time(), aviso or Aviso.HORARIO_PEDIDO_INDISPONIVEL
            horarios = self._buscar(medicos, criterios, recusados)
        if not horarios:
            return ResultadoDialogo(
                TipoResultado.SEM_HORARIOS,
                especialidade=criterios.especialidade or medicos[0].especialidade,
                periodo=_periodo_de(criterios),
                acao_pendente=AcaoPendente(tipo=TipoAcao.AGENDAR, criterios=criterios),
            )
        horario = horarios[0]
        medico = next(medico for medico in medicos if medico.id == horario.medico_id)
        return ResultadoDialogo(
            TipoResultado.SUGESTAO_HORARIO,
            opcao=OpcaoAgenda.from_horario(horario, medico),
            aviso=aviso,
            acao_pendente=AcaoPendente(
                tipo=TipoAcao.AGENDAR, horario_id=horario.id, criterios=criterios, recusados=list(recusados)
            ),
        )

    def _buscar(
        self, medicos: Sequence[Medico], criterios: CriteriosAgendamento, recusados: Sequence[int]
    ) -> list[Horario]:
        return self.agenda.next_available(
            [medico.id for medico in medicos],
            data_inicio=criterios.data_inicio,
            data_fim=criterios.data_fim,
            hora=criterios.hora,
            turno=criterios.turno,
            excluir=recusados,
        )

    def _reservar(
        self, horario: Horario, paciente: Paciente, criterios: CriteriosAgendamento, recusados: Sequence[int] = ()
    ) -> ResultadoDialogo:
        try:
            consulta = self.consultas.create(
                ConsultaCreate(
                    paciente_id=paciente.id,
                    medico_id=horario.medico_id,
                    horario_id=horario.id,
                    data=horario.data,
                    observacao=self.OBSERVACAO_AGENDAMENTO,
                )
            )
        except HorarioIndisponivelError as erro:
            return self._alternativa_apos_conflito(horario, criterios, [*recusados, horario.id], erro.detail)
        except DomainError as erro:
            return ResultadoDialogo(TipoResultado.REGRA_VIOLADA, detalhe=erro.detail)
        detalhada = self._detalhar(consulta.id)
        return ResultadoDialogo(
            TipoResultado.CONSULTA_AGENDADA,
            opcao=OpcaoAgenda.from_consulta(detalhada, horario.id),
            consulta=detalhada,
        )

    def _alternativa_apos_conflito(
        self, horario: Horario, criterios: CriteriosAgendamento, recusados: Sequence[int], detalhe: str
    ) -> ResultadoDialogo:
        medicos, falha = self._resolver_medicos(criterios)
        if falha:
            medicos = [medico for medico in self.agenda.medicos.list_all() if medico.id == horario.medico_id]
        sugestao = self._sugerir(medicos, criterios.without_time(), recusados, Aviso.HORARIO_RESERVADO)
        if sugestao.tipo == TipoResultado.SUGESTAO_HORARIO:
            return sugestao
        return ResultadoDialogo(TipoResultado.HORARIO_RESERVADO, detalhe=detalhe)

    def _executar(self, pendente: AcaoPendente, paciente: Paciente) -> ResultadoDialogo:
        if pendente.tipo == TipoAcao.CANCELAR:
            return self._cancelar(paciente, pendente.consulta_id)
        horario = self.agenda.horarios.get_by_id(pendente.horario_id) if pendente.horario_id else None
        if horario is None:
            return self._agendar(paciente, pendente.criterios, pendente.recusados)
        return self._reservar(horario, paciente, pendente.criterios, pendente.recusados)

    def _solicitar_cancelamento(self, paciente: Paciente, entidades: Entidades) -> ResultadoDialogo:
        candidatas = self._filtrar(self._consultas_futuras(paciente), entidades)
        if not candidatas:
            referencia = IntervaloDatas(entidades.data, entidades.data) if entidades.data else entidades.periodo
            return ResultadoDialogo(TipoResultado.CONSULTA_NAO_ENCONTRADA, periodo=referencia)
        if len(candidatas) > 1:
            return ResultadoDialogo(TipoResultado.CANCELAMENTO_AMBIGUO, opcoes=tuple(candidatas))
        alvo = candidatas[0]
        return ResultadoDialogo(
            TipoResultado.CONFIRMAR_CANCELAMENTO,
            opcao=alvo,
            acao_pendente=AcaoPendente(tipo=TipoAcao.CANCELAR, consulta_id=alvo.consulta_id),
        )

    def _cancelar(self, paciente: Paciente, consulta_id: int | None) -> ResultadoDialogo:
        consulta = self.consultas_repository.get_by_id(consulta_id) if consulta_id else None
        if consulta is None or consulta.paciente_id != paciente.id:
            return ResultadoDialogo(TipoResultado.CONSULTA_NAO_ENCONTRADA)
        try:
            self.consultas.cancel(consulta.id, ConfirmacaoConsulta(confirmado=True))
        except DomainError:
            return ResultadoDialogo(TipoResultado.CONSULTA_NAO_ENCONTRADA)
        self.notificacoes.avisar_equipe_sobre_cancelamento(consulta.id)
        detalhada = self._detalhar(consulta.id)
        return ResultadoDialogo(
            TipoResultado.CONSULTA_CANCELADA,
            opcao=OpcaoAgenda.from_consulta(detalhada, consulta.horario_id),
            consulta=detalhada,
        )

    def _apresentar_solicitacao(self, paciente: Paciente, vistas: Sequence[int]) -> ResultadoDialogo | None:
        notificacao = NotificacaoRepository(self.db).proxima_solicitacao(paciente.usuario_id, vistas)
        if notificacao is None:
            return None
        _, horario, medico, _ = self.consultas_repository.get_da_agenda(notificacao.consulta_id)
        remarcacao = notificacao.tipo == TipoNotificacao.REAGENDAMENTO_PENDENTE
        return ResultadoDialogo(
            TipoResultado.SOLICITACAO_REMARCACAO if remarcacao else TipoResultado.SOLICITACAO_CANCELAMENTO,
            opcao=OpcaoAgenda.from_horario(horario, medico),
            opcao_nova=self._opcao_do_horario_novo(notificacao) if remarcacao else None,
            detalhe=self.db.get(Usuario, notificacao.solicitante_id).nome if notificacao.solicitante_id else None,
            acao_pendente=AcaoPendente(tipo=TipoAcao.RESPONDER_SOLICITACAO, notificacao_id=notificacao.id),
        )

    def _opcao_do_horario_novo(self, notificacao: Notificacao) -> OpcaoAgenda:
        novo = notificacao.horario_novo
        return OpcaoAgenda.from_horario(novo, self.db.get(Medico, novo.medico_id))

    def _responder_solicitacao(self, paciente: Paciente, notificacao_id: int | None, aceitar: bool) -> ResultadoDialogo:
        usuario = self.db.get(Usuario, paciente.usuario_id)
        try:
            resposta = self.notificacoes.responder(notificacao_id, usuario, aceitar)
        except DomainError as erro:
            return ResultadoDialogo(TipoResultado.REGRA_VIOLADA, detalhe=erro.detail)
        if not aceitar:
            return ResultadoDialogo(TipoResultado.SOLICITACAO_RECUSADA)
        if resposta.tipo == TipoNotificacao.REAGENDAMENTO_PENDENTE:
            return ResultadoDialogo(TipoResultado.REMARCACAO_ACEITA)
        return ResultadoDialogo(TipoResultado.CANCELAMENTO_ACEITO)

    def _listar(self, paciente: Paciente) -> ResultadoDialogo:
        futuras = self._consultas_futuras(paciente)
        if not futuras:
            return ResultadoDialogo(TipoResultado.SEM_CONSULTAS)
        return ResultadoDialogo(TipoResultado.LISTA_CONSULTAS, opcoes=tuple(futuras))

    def _consultas_futuras(self, paciente: Paciente) -> list[OpcaoAgenda]:
        detalhadas = self.consultas_repository.list_detalhadas_by_paciente(
            paciente.id, desde_data=self.clock.today().isoformat(), apenas_agendadas=True
        )
        return [
            OpcaoAgenda.from_consulta(ConsultaDetalhadaOut.from_models(consulta, horario, medico), horario.id)
            for consulta, horario, medico in detalhadas
        ]

    def _detalhar(self, consulta_id: int) -> ConsultaDetalhadaOut:
        consulta, horario, medico = self.consultas_repository.get_detalhada(consulta_id)
        return ConsultaDetalhadaOut.from_models(consulta, horario, medico)

    @staticmethod
    def _filtrar(opcoes: list[OpcaoAgenda], entidades: Entidades) -> list[OpcaoAgenda]:
        especialidade = buscar_especialidade(entidades.especialidade) if entidades.especialidade else None
        return [
            opcao
            for opcao in opcoes
            if (entidades.data is None or opcao.data == entidades.data)
            and (entidades.periodo is None or entidades.periodo.inicio <= opcao.data <= entidades.periodo.fim)
            and (entidades.hora is None or opcao.hora == entidades.hora)
            and (entidades.medico is None or normalizar(entidades.medico) in normalizar(opcao.medico))
            and (especialidade is None or especialidade.corresponde_a(opcao.especialidade))
        ]

    def _resolver_medicos(self, criterios: CriteriosAgendamento) -> tuple[list[Medico], ResultadoDialogo | None]:
        pendente = AcaoPendente(tipo=TipoAcao.AGENDAR, criterios=criterios)
        if criterios.medico_nome:
            encontrados = self.agenda.find_doctors_by_name(criterios.medico_nome)
            if criterios.especialidade and (especialidade := buscar_especialidade(criterios.especialidade)):
                encontrados = [m for m in encontrados if especialidade.corresponde_a(m.especialidade)] or encontrados
            if not encontrados:
                return [], ResultadoDialogo(TipoResultado.MEDICO_NAO_ENCONTRADO, acao_pendente=pendente)
            if len(encontrados) > 1:
                nomes = tuple(medico.nome for medico in encontrados)
                return [], ResultadoDialogo(TipoResultado.MEDICO_AMBIGUO, medicos=nomes, acao_pendente=pendente)
            return encontrados, None
        if criterios.especialidade:
            encontrados = self.agenda.find_doctors_by_specialty(criterios.especialidade)
            if not encontrados:
                return [], ResultadoDialogo(
                    TipoResultado.SEM_HORARIOS,
                    especialidade=criterios.especialidade,
                    periodo=_periodo_de(criterios),
                    acao_pendente=pendente,
                )
            return encontrados, None
        return [], ResultadoDialogo(TipoResultado.FALTA_ESPECIALIDADE, acao_pendente=pendente)
