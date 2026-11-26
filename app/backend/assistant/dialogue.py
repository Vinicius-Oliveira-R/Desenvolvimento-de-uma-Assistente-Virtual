"""Tipos do diálogo e operações de agenda usadas pela conversa.

Toda escrita passa pelos serviços transacionais e é precedida de nova conferência do
paciente, da consulta e da disponibilidade. Repetições (clique duplo, conexão que caiu
após o envio) não criam segunda reserva: a resposta informa o que já está registrado.
"""
from collections.abc import Sequence
from dataclasses import dataclass, replace
from datetime import date
from enum import StrEnum

from sqlalchemy.orm import Session

from app.backend.assistant.especialidades import ESPECIALIDADE_PADRAO, buscar_especialidade
from app.backend.assistant.nlp import Entidades
from app.backend.assistant.temporal import IntervaloDatas
from app.backend.core.clock import Clock
from app.backend.core.exceptions import ConflictError, DomainError, HorarioIndisponivelError
from app.backend.core.text import normalizar
from app.backend.models import Horario, Medico, Paciente, StatusConsulta, Usuario
from app.backend.models.notificacao import Notificacao, StatusNotificacao, TipoNotificacao
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
    ESCLARECER_OPCAO = "esclarecer_opcao"
    HORARIO_RESERVADO = "horario_reservado"
    SEM_HORARIOS = "sem_horarios"
    SEM_PROFISSIONAL = "sem_profissional"
    MEDICO_NAO_ENCONTRADO = "medico_nao_encontrado"
    MEDICO_AMBIGUO = "medico_ambiguo"
    FALTA_ESPECIALIDADE = "falta_especialidade"
    CONFIRMAR_CANCELAMENTO = "confirmar_cancelamento"
    CONSULTA_CANCELADA = "consulta_cancelada"
    CONSULTA_NAO_ENCONTRADA = "consulta_nao_encontrada"
    CANCELAMENTO_AMBIGUO = "cancelamento_ambiguo"
    GERENCIAR_CONSULTAS = "gerenciar_consultas"
    ESCOLHER_ACAO = "escolher_acao"
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
    SOLICITACAO_INDISPONIVEL = "solicitacao_indisponivel"
    REMARCACAO_ACEITA = "remarcacao_aceita"
    CANCELAMENTO_ACEITO = "cancelamento_aceito"
    SOLICITACAO_RECUSADA = "solicitacao_recusada"


class Aviso(StrEnum):
    """Informações que precisam aparecer antes da escolha."""

    ESPECIALIDADE_PADRAO = "especialidade_padrao"
    HORARIO_RESERVADO = "horario_reservado"
    HORARIO_PEDIDO_INDISPONIVEL = "horario_pedido_indisponivel"
    FORA_DO_PERIODO = "fora_do_periodo"
    OPCOES_REDUZIDAS = "opcoes_reduzidas"
    ESCOLHA_AUTOMATICA = "escolha_automatica"


class Preambulo(StrEnum):
    """Frase que antecede a reapresentação da etapa atual, sem mudar a agenda."""

    AJUDA = "ajuda"
    SITUACAO = "situacao"
    NAO_ENTENDI = "nao_entendi"
    RETOMADA = "retomada"
    BOTAO_ANTIGO = "botao_antigo"
    ESTILO_PASSO_A_PASSO = "estilo_passo_a_passo"
    ESTILO_DIRETO = "estilo_direto"
    ESTILO_AUTOMATICO = "estilo_automatico"
    MAIS_OPCOES = "mais_opcoes"
    LIMITE_MEDICO = "limite_medico"
    SOCIAL = "social"
    OPCAO_INEXISTENTE = "opcao_inexistente"
    ESCOLHA_PENDENTE = "escolha_pendente"
    JA_REGISTRADA = "ja_registrada"
    CONSULTA_MUDOU = "consulta_mudou"


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
    consulta_atual: OpcaoAgenda | None = None
    opcoes: tuple[OpcaoAgenda, ...] = ()
    avisos: tuple[Aviso, ...] = ()
    preambulo: Preambulo | None = None
    especialidade: str | None = None
    periodo: IntervaloDatas | None = None
    pedido: CriteriosAgendamento | None = None
    medicos: tuple[str, ...] = ()
    detalhe: str | None = None
    numero: int | None = None
    hora_mencionada: str | None = None
    dia: date | None = None
    acao_pendente: AcaoPendente | None = None
    consulta: ConsultaDetalhadaOut | None = None


MAX_REJECTIONS = 120


def limitar(recusados: Sequence[int], manter: int | None = None) -> list[int]:
    """Mantém os últimos recusados dentro do limite do contexto (e a consulta de origem, se houver)."""
    unicos = [horario for horario in dict.fromkeys(recusados) if horario != manter]
    if manter is None:
        return unicos[-MAX_REJECTIONS:]
    return [manter, *unicos[-(MAX_REJECTIONS - 1):]]


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


def periodo_de(criterios: CriteriosAgendamento) -> IntervaloDatas | None:
    if criterios.data_inicio is None:
        return None
    return IntervaloDatas(criterios.data_inicio, criterios.data_fim or criterios.data_inicio)


class DialogueManager:
    """Operações de agenda; a interpretação da conversa fica em SchedulingDialogueManager."""

    OBSERVACAO_AGENDAMENTO = "Agendamento realizado pelo assistente virtual"

    def __init__(self, db: Session, clock: Clock):
        self.clock = clock
        self.agenda = AgendaService(db, clock)
        self.consultas = ConsultaService(db)
        self.consultas_repository = ConsultaRepository(db)
        self.notificacoes = NotificacaoService(db)
        self.notificacoes_repository = NotificacaoRepository(db)
        self.db = db

    def _reservar(self, horario: Horario, paciente: Paciente) -> ResultadoDialogo | None:
        """Grava a consulta; devolve None quando a vaga foi ocupada por outra pessoa."""
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
        except HorarioIndisponivelError:
            return self._ja_registrada(paciente, horario.id)
        except ConflictError:
            return self._ja_registrada(paciente, horario.id) or ResultadoDialogo(TipoResultado.HORARIO_RESERVADO)
        except DomainError as erro:
            return ResultadoDialogo(TipoResultado.REGRA_VIOLADA, detalhe=erro.detail)
        detalhada = self._detalhar(consulta.id)
        return ResultadoDialogo(
            TipoResultado.CONSULTA_AGENDADA, opcao=OpcaoAgenda.from_consulta(detalhada, horario.id), consulta=detalhada
        )

    def _ja_registrada(self, paciente: Paciente, horario_id: int) -> ResultadoDialogo | None:
        consulta = self.consultas_repository.get_ativa_por_horario(horario_id)
        if consulta is None or consulta.paciente_id != paciente.id:
            return None
        detalhada = self._detalhar(consulta.id)
        return ResultadoDialogo(
            TipoResultado.CONSULTA_AGENDADA,
            opcao=OpcaoAgenda.from_consulta(detalhada, horario_id),
            consulta=detalhada,
            preambulo=Preambulo.JA_REGISTRADA,
        )

    def _cancelar(self, paciente: Paciente, consulta_id: int | None) -> ResultadoDialogo:
        consulta = self.consultas_repository.get_by_id(consulta_id) if consulta_id else None
        if consulta is None or consulta.paciente_id != paciente.id:
            return ResultadoDialogo(TipoResultado.CONSULTA_NAO_ENCONTRADA)
        if consulta.status == StatusConsulta.CANCELADA:
            return self._cancelada(consulta.id, consulta.horario_id, preambulo=Preambulo.JA_REGISTRADA)
        if consulta.status != StatusConsulta.AGENDADA:
            return ResultadoDialogo(TipoResultado.CONSULTA_NAO_ENCONTRADA)
        try:
            self.consultas.cancel(consulta.id, ConfirmacaoConsulta(confirmado=True))
        except ConflictError:
            return self._cancelada(consulta.id, consulta.horario_id, preambulo=Preambulo.JA_REGISTRADA)
        except DomainError:
            return ResultadoDialogo(TipoResultado.CONSULTA_NAO_ENCONTRADA)
        self.notificacoes.avisar_equipe_sobre_cancelamento(consulta.id)
        return self._cancelada(consulta.id, consulta.horario_id)

    def _cancelada(self, consulta_id: int, horario_id: int, preambulo: Preambulo | None = None) -> ResultadoDialogo:
        detalhada = self._detalhar(consulta_id)
        return ResultadoDialogo(
            TipoResultado.CONSULTA_CANCELADA,
            opcao=OpcaoAgenda.from_consulta(detalhada, horario_id),
            consulta=detalhada,
            preambulo=preambulo,
        )

    def _apresentar_solicitacao(self, paciente: Paciente, vistas: Sequence[int]) -> ResultadoDialogo | None:
        notificacao = self.notificacoes_repository.proxima_solicitacao(paciente.usuario_id, vistas)
        return self._resultado_da_solicitacao(notificacao) if notificacao else None

    def _resultado_da_solicitacao(self, notificacao: Notificacao) -> ResultadoDialogo | None:
        linha = self.consultas_repository.get_da_agenda(notificacao.consulta_id)
        if linha is None:
            return None
        _, horario, medico, _ = linha
        remarcacao = notificacao.tipo == TipoNotificacao.REAGENDAMENTO_PENDENTE
        solicitante = self.db.get(Usuario, notificacao.solicitante_id) if notificacao.solicitante_id else None
        return ResultadoDialogo(
            TipoResultado.SOLICITACAO_REMARCACAO if remarcacao else TipoResultado.SOLICITACAO_CANCELAMENTO,
            opcao=OpcaoAgenda.from_horario(horario, medico),
            opcao_nova=self._opcao_do_horario_novo(notificacao) if remarcacao else None,
            detalhe=solicitante.nome if solicitante else None,
            acao_pendente=AcaoPendente(
                tipo=TipoAcao.RESPONDER_SOLICITACAO,
                notificacao_id=notificacao.id,
                consulta_id=notificacao.consulta_id,
                origem_horario_id=horario.id,
                solicitacao="remarcacao" if remarcacao else "cancelamento",
            ),
        )

    def _opcao_do_horario_novo(self, notificacao: Notificacao) -> OpcaoAgenda:
        novo = notificacao.horario_novo
        return OpcaoAgenda.from_horario(novo, self.db.get(Medico, novo.medico_id))

    def _solicitacao_pendente(self, paciente: Paciente, notificacao_id: int | None) -> Notificacao | None:
        notificacao = self.db.get(Notificacao, notificacao_id) if notificacao_id else None
        if (
            notificacao is None
            or notificacao.usuario_destino_id != paciente.usuario_id
            or notificacao.status != StatusNotificacao.PENDENTE
            or not notificacao.e_solicitacao
        ):
            return None
        return notificacao

    def _responder_solicitacao(
        self, paciente: Paciente, notificacao_id: int | None, aceitar: bool, horario_exibido: int | None = None
    ) -> ResultadoDialogo:
        notificacao = self._solicitacao_pendente(paciente, notificacao_id)
        if notificacao is None:
            return ResultadoDialogo(TipoResultado.REGRA_VIOLADA, detalhe="Esse pedido da clínica já foi respondido.")
        anterior = self._resultado_da_solicitacao(notificacao)
        mudou = anterior is None or (horario_exibido is not None and anterior.opcao.horario_id != horario_exibido)
        if aceitar and mudou:
            # A consulta mudou depois que o pedido foi mostrado: nada é aceito sem mostrar o horário atual.
            return replace(anterior, preambulo=Preambulo.CONSULTA_MUDOU) if anterior else ResultadoDialogo(
                TipoResultado.CONSULTA_NAO_ENCONTRADA
            )
        usuario = self.db.get(Usuario, paciente.usuario_id)
        try:
            self.notificacoes.responder(notificacao.id, usuario, aceitar)
        except HorarioIndisponivelError:
            return ResultadoDialogo(TipoResultado.SOLICITACAO_INDISPONIVEL, opcao=anterior.opcao if anterior else None)
        except DomainError as erro:
            return ResultadoDialogo(TipoResultado.REGRA_VIOLADA, detalhe=erro.detail)
        atual = anterior.opcao if anterior else None
        if not aceitar:
            return ResultadoDialogo(TipoResultado.SOLICITACAO_RECUSADA, opcao=atual)
        if notificacao.tipo == TipoNotificacao.REAGENDAMENTO_PENDENTE:
            detalhada = self._detalhar(notificacao.consulta_id)
            return ResultadoDialogo(
                TipoResultado.REMARCACAO_ACEITA,
                consulta_atual=atual,
                opcao=OpcaoAgenda.from_consulta(detalhada, notificacao.horario_novo_id),
                consulta=detalhada,
            )
        return ResultadoDialogo(TipoResultado.CANCELAMENTO_ACEITO, opcao=atual)

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

    def _consulta_do_paciente(self, paciente: Paciente, consulta_id: int | None) -> OpcaoAgenda | None:
        return next((opcao for opcao in self._consultas_futuras(paciente) if opcao.consulta_id == consulta_id), None)

    def _detalhar(self, consulta_id: int) -> ConsultaDetalhadaOut:
        consulta, horario, medico = self.consultas_repository.get_detalhada(consulta_id)
        return ConsultaDetalhadaOut.from_models(consulta, horario, medico)

    @staticmethod
    def _filtrar(opcoes: list[OpcaoAgenda], entidades: Entidades) -> list[OpcaoAgenda]:
        especialidade = buscar_especialidade(entidades.especialidade) if entidades.especialidade else None
        return [
            opcao
            for opcao in opcoes
            if (entidades.dia_semana is None or opcao.data.weekday() == entidades.dia_semana)
            and (entidades.dia_semana is not None or entidades.data is None or opcao.data == entidades.data)
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
                return [], self._sem_profissional(criterios.especialidade)
            return encontrados, None
        return [], ResultadoDialogo(TipoResultado.FALTA_ESPECIALIDADE, acao_pendente=pendente)

    @staticmethod
    def _sem_profissional(especialidade: str) -> ResultadoDialogo:
        """Não há médico ativo na especialidade: diferente de "sem vaga" e de "vaga ocupada agora"."""
        alternativa = None
        if normalizar(especialidade) != normalizar(ESPECIALIDADE_PADRAO):
            alternativa = AcaoPendente(
                tipo=TipoAcao.AGENDAR,
                origem=TipoResultado.SEM_PROFISSIONAL,
                criterios=CriteriosAgendamento(especialidade=ESPECIALIDADE_PADRAO),
                pedido=CriteriosAgendamento(especialidade=especialidade),
            )
        return ResultadoDialogo(TipoResultado.SEM_PROFISSIONAL, especialidade=especialidade, acao_pendente=alternativa)
