"""Conversa de agenda: listar -> escolher -> confirmar -> gravar.

Texto e botões passam pelo mesmo LeitorDeRespostas e pela mesma validação da pergunta
pendente. Só as perguntas de confirmação alteram a agenda, depois de conferir de novo o
paciente, a consulta e a vaga. Dúvidas reapresentam a etapa sem mudar nada; um botão de
uma pergunta anterior (proposta diferente) nunca confirma a proposta mais recente.
"""

import re
from collections.abc import Sequence
from dataclasses import replace
from datetime import date

from app.backend.assistant.dialogue import (
    MAX_REJECTIONS,
    Aviso,
    DialogueManager,
    OpcaoAgenda,
    Preambulo,
    ResultadoDialogo,
    TipoResultado,
    criterios_de,
    limitar,
    periodo_de,
)
from app.backend.assistant.especialidades import ESPECIALIDADE_PADRAO
from app.backend.assistant.managing import GerenciamentoDeConsultas
from app.backend.assistant.nlp import Intencao, MensagemInterpretada, MessageInterpreter
from app.backend.assistant.replies import ContextoDaLeitura, LeitorDeRespostas, Leitura, TipoLeitura, Verbo
from app.backend.assistant.rescheduling import AtomicRescheduling
from app.backend.assistant.scheduling_language import analyze_scheduling, normalize_schedule_text
from app.backend.assistant.temporal import TURNOS, TemporalResolver
from app.backend.models import Horario, Medico, Paciente
from app.backend.schemas.assistant import AcaoDeBotao, AcaoPendente, CriteriosAgendamento, Pergunta, TipoAcao

PAGE_SIZE = 6
_DESTINO_DA_REMARCACAO = re.compile(r"\b(?:para|pra|pro)\b", re.IGNORECASE)
_ACOES = (Intencao.AGENDAR, Intencao.CANCELAR, Intencao.REMARCAR, Intencao.LISTAR)
_PERGUNTAS_SOBRE_HORARIOS = (Pergunta.ESCOLHER_HORARIO, Pergunta.CONFIRMAR_HORARIO, Pergunta.CONFIRMAR_TROCA)

BOTOES_POR_PERGUNTA: dict[Pergunta, frozenset[str]] = {
    Pergunta.NOVA_BUSCA: frozenset({"buscar_horarios", "nao_marcar"}),
    Pergunta.ESCOLHER_HORARIO: frozenset({"escolher", "outro_horario", "nao_marcar", "manter_consulta", "buscar_dia"}),
    Pergunta.CONFIRMAR_HORARIO: frozenset({"confirmar_horario", "outro_horario", "nao_marcar", "escolher"}),
    Pergunta.INFORMAR_DESTINO: frozenset({"buscar_horarios", "manter_consulta"}),
    Pergunta.CONFIRMAR_TROCA: frozenset({"confirmar_troca", "manter_consulta", "outro_horario", "escolher"}),
    Pergunta.CONFIRMAR_DESMARCACAO: frozenset({"desmarcar_consulta", "manter_consulta"}),
    Pergunta.ESCOLHER_CONSULTA: frozenset({"escolher", "manter_consulta"}),
    Pergunta.ESCOLHER_ACAO: frozenset({"mudar_horario", "desmarcar_esta", "manter_consulta"}),
    Pergunta.RESPONDER_SOLICITACAO: frozenset({"confirmar_troca", "desmarcar_consulta", "manter_consulta"}),
}
_LEITURA_DO_BOTAO = {
    "confirmar_horario": TipoLeitura.CONFIRMA,
    "confirmar_troca": TipoLeitura.CONFIRMA,
    "desmarcar_consulta": TipoLeitura.CONFIRMA,
    "buscar_horarios": TipoLeitura.CONFIRMA,
    "manter_consulta": TipoLeitura.NEGA,
    "nao_marcar": TipoLeitura.NEGA,
    "outro_horario": TipoLeitura.OUTRA_OPCAO,
}
_VERBO_DA_ACAO = {
    TipoAcao.AGENDAR: Verbo.AGENDAR,
    TipoAcao.REMARCAR: Verbo.REMARCAR,
    TipoAcao.CANCELAR: Verbo.CANCELAR,
    TipoAcao.GERENCIAR: Verbo.REMARCAR,
}


class SchedulingMessageInterpreter(MessageInterpreter):
    """Acrescenta linguagem de agenda sem substituir as entidades do spaCy."""

    def interpret(self, texto: str) -> MensagemInterpretada:
        message = super().interpret(texto)
        language = analyze_scheduling(texto)
        if message.intencao == Intencao.REMARCAR:
            return self._com_origem_e_destino(message)
        # Não converte cancelamento ou orientação médica em marcação.
        if message.intencao in (Intencao.CANCELAR, Intencao.ORIENTACAO_MEDICA):
            return message
        if language.own_appointments:
            return replace(message, intencao=Intencao.LISTAR)
        if language.decline:
            return replace(message, intencao=Intencao.NEGAR, negativa=True, afirmativa=False)
        if message.intencao == Intencao.LISTAR:
            return message
        if language.availability or language.booking or language.no_preference or message.sem_preferencia:
            return replace(
                message,
                intencao=Intencao.AGENDAR,
                sem_preferencia=message.sem_preferencia or language.no_preference,
                negativa=False if language.no_preference or message.sem_preferencia else message.negativa,
            )
        # Uma data/um turno isolados também servem para consultar a agenda.
        if message.intencao == Intencao.DESCONHECIDA and message.entidades.possui_criterios:
            return replace(message, intencao=Intencao.AGENDAR)
        return message

    def _com_origem_e_destino(self, message: MensagemInterpretada) -> MensagemInterpretada:
        """ "Mudar a consulta de sexta para segunda à tarde": origem antes do "para", destino depois."""
        partes = _DESTINO_DA_REMARCACAO.split(message.texto, maxsplit=1)
        if len(partes) != 2:
            return replace(message, origem=message.entidades)
        origem, destino = (self._extrair_entidades(self._processor.analyze(parte)[0]) for parte in partes)
        return replace(message, origem=origem, destino=destino)


class SchedulingDialogueManager(GerenciamentoDeConsultas, AtomicRescheduling, DialogueManager):
    page_size = PAGE_SIZE

    def __init__(self, db, clock):
        super().__init__(db, clock)
        self.leitor = LeitorDeRespostas(TemporalResolver(clock).dia_da_semana)

    # ---------------------------------------------------------------- entrada
    def handle(
        self,
        mensagem: MensagemInterpretada,
        paciente: Paciente,
        pendente: AcaoPendente | None,
        solicitacoes_vistas: Sequence[int] = (),
        botao: AcaoDeBotao | None = None,
    ) -> ResultadoDialogo:
        if botao is not None:
            return self._tratar_botao(botao, mensagem, paciente, pendente)
        if pendente is None:
            return self._apresentar_solicitacao(paciente, solicitacoes_vistas) or self._rotear(mensagem, paciente)
        if mensagem.intencao == Intencao.ORIENTACAO_MEDICA:
            return self.reapresentar(paciente, pendente, Preambulo.LIMITE_MEDICO)
        leitura = self._ler(mensagem, paciente, pendente)
        resultado = self._responder(leitura, mensagem, paciente, pendente)
        if resultado is None:
            resultado = self._continuar(mensagem, paciente, pendente)
        return resultado or self._rotear(mensagem, paciente)

    def retomar(self, paciente: Paciente, pendente: AcaoPendente | None, vistas: Sequence[int]) -> ResultadoDialogo:
        """Atualizar a página reapresenta a etapa e revalida a vaga; sem etapa, abre a conversa."""
        if pendente is not None:
            return self.reapresentar(paciente, pendente, Preambulo.RETOMADA)
        return self._apresentar_solicitacao(paciente, vistas) or ResultadoDialogo(TipoResultado.SAUDACAO)

    def mudar_apresentacao(
        self, paciente: Paciente, pendente: AcaoPendente | None, preambulo: Preambulo
    ) -> ResultadoDialogo:
        """Mudar a forma de explicar não muda a agenda: a pergunta pendente é reapresentada."""
        if pendente is None:
            return ResultadoDialogo(TipoResultado.SAUDACAO, preambulo=preambulo)
        if preambulo == Preambulo.MAIS_OPCOES and pendente.pergunta == Pergunta.ESCOLHER_HORARIO:
            avisos = tuple(Aviso(aviso) for aviso in pendente.avisos if aviso != Aviso.OPCOES_REDUZIDAS)
            busca = self._sugerir_criterios(
                self._default_target(pendente.criterios), pendente.recusados, avisos, pendente.pedido
            )
            return replace(self._no_fluxo(pendente, busca), preambulo=preambulo)
        return self.reapresentar(paciente, pendente, preambulo)

    def reapresentar(
        self,
        paciente: Paciente,
        pendente: AcaoPendente,
        preambulo: Preambulo | None = None,
        numero: int | None = None,
        hora: str | None = None,
    ) -> ResultadoDialogo:
        resultado = self._etapa_atual(paciente, pendente)
        return replace(
            resultado,
            preambulo=preambulo,
            numero=resultado.numero if numero is None else numero,
            hora_mencionada=hora,
        )

    # ---------------------------------------------------------------- botões
    def _tratar_botao(
        self, botao: AcaoDeBotao, mensagem: MensagemInterpretada, paciente: Paciente, pendente: AcaoPendente | None
    ) -> ResultadoDialogo:
        if botao.codigo == "marcar_consulta":
            return self._agendar_pedido(paciente, CriteriosAgendamento())
        if botao.codigo == "minhas_consultas":
            return self._listar(paciente)
        if botao.codigo == "mudar_ou_cancelar":
            return self.gerenciar(paciente)
        if pendente is None or botao.proposta is None or botao.proposta != pendente.proposta:
            return self._botao_antigo(paciente, pendente)
        if botao.codigo not in BOTOES_POR_PERGUNTA[pendente.pergunta]:
            return self._botao_antigo(paciente, pendente)
        if botao.codigo in ("mudar_horario", "desmarcar_esta"):
            return self._executar_acao_escolhida(paciente, pendente, mudar=botao.codigo == "mudar_horario")
        leitura = self._leitura_do_botao(botao, pendente)
        if leitura is None:
            return self._botao_antigo(paciente, pendente)
        return self._responder(leitura, mensagem, paciente, pendente) or self.reapresentar(
            paciente, pendente, Preambulo.NAO_ENTENDI
        )

    @staticmethod
    def _leitura_do_botao(botao: AcaoDeBotao, pendente: AcaoPendente) -> Leitura | None:
        if pendente.pergunta == Pergunta.RESPONDER_SOLICITACAO and botao.codigo != "manter_consulta":
            esperado = "confirmar_troca" if pendente.solicitacao == "remarcacao" else "desmarcar_consulta"
            if botao.codigo != esperado:
                return None
        if botao.codigo == "escolher":
            indice = int(botao.valor) if botao.valor and botao.valor.isdigit() else 0
            exibidas = (
                pendente.consultas_oferecidas if pendente.pergunta == Pergunta.ESCOLHER_CONSULTA
                else pendente.horarios_oferecidos
            )
            return Leitura(TipoLeitura.ESCOLHA, indices=(indice,)) if 1 <= indice <= len(exibidas) else None
        if botao.codigo == "buscar_dia":
            if pendente.duvida_dia is None or botao.valor != pendente.duvida_dia.isoformat():
                return None
            return Leitura(TipoLeitura.BUSCAR_DIA, dia=pendente.duvida_dia)
        return Leitura(_LEITURA_DO_BOTAO[botao.codigo])

    def _botao_antigo(self, paciente: Paciente, pendente: AcaoPendente | None) -> ResultadoDialogo:
        if pendente is None:
            return ResultadoDialogo(TipoResultado.SAUDACAO, preambulo=Preambulo.BOTAO_ANTIGO)
        return self.reapresentar(paciente, pendente, Preambulo.BOTAO_ANTIGO)

    # ---------------------------------------------------------------- leitura de texto
    def _ler(self, mensagem: MensagemInterpretada, paciente: Paciente, pendente: AcaoPendente) -> Leitura:
        if pendente.tipo == TipoAcao.RESPONDER_SOLICITACAO:
            verbo = Verbo.REMARCAR if pendente.solicitacao == "remarcacao" else Verbo.CANCELAR
        else:
            verbo = _VERBO_DA_ACAO[pendente.tipo]
        consultas = pendente.pergunta == Pergunta.ESCOLHER_CONSULTA
        contexto = ContextoDaLeitura(
            verbo=verbo,
            opcoes=self._consultas_exibidas(paciente, pendente) if consultas else self._horarios_exibidos(pendente),
            opcoes_sao_horarios=not consultas,
            escolhendo=pendente.pergunta == Pergunta.ESCOLHER_HORARIO,
            confirmando=pendente.confirmacao_pendente,
            duvida_opcao=pendente.duvida_opcao,
            duvida_dia=pendente.duvida_dia,
        )
        return self.leitor.ler(mensagem.texto, mensagem.intencao, mensagem.entidades, contexto)

    def _responder(
        self, leitura: Leitura, mensagem: MensagemInterpretada, paciente: Paciente, pendente: AcaoPendente
    ) -> ResultadoDialogo | None:
        if leitura.tipo == TipoLeitura.DUVIDA:
            preambulo = Preambulo.SITUACAO if leitura.sobre_situacao else Preambulo.AJUDA
            return self.reapresentar(paciente, pendente, preambulo)
        if leitura.tipo == TipoLeitura.SOCIAL:
            return self.reapresentar(paciente, pendente, Preambulo.SOCIAL)
        if leitura.tipo == TipoLeitura.OPCAO_INEXISTENTE:
            return self.reapresentar(paciente, pendente, Preambulo.OPCAO_INEXISTENTE, leitura.numero, leitura.hora)
        match pendente.pergunta:
            case Pergunta.RESPONDER_SOLICITACAO:
                return self._responder_pedido_da_clinica(leitura, mensagem, paciente, pendente)
            case Pergunta.CONFIRMAR_DESMARCACAO:
                return self._responder_desmarcacao(leitura, mensagem, paciente, pendente)
            case Pergunta.ESCOLHER_CONSULTA:
                return self._responder_escolha_de_consulta(leitura, mensagem, paciente, pendente)
            case Pergunta.ESCOLHER_ACAO:
                return self._responder_acao_da_consulta(leitura, mensagem, paciente, pendente)
        return self._responder_sobre_horarios(leitura, mensagem, paciente, pendente)

    def _responder_pedido_da_clinica(
        self, leitura: Leitura, mensagem: MensagemInterpretada, paciente: Paciente, pendente: AcaoPendente
    ) -> ResultadoDialogo | None:
        if leitura.tipo in (TipoLeitura.CONFIRMA, TipoLeitura.NEGA):
            aceitar = leitura.tipo == TipoLeitura.CONFIRMA
            return self._responder_solicitacao(paciente, pendente.notificacao_id, aceitar, pendente.origem_horario_id)
        if mensagem.intencao in _ACOES:
            return None
        return self.reapresentar(paciente, pendente, Preambulo.NAO_ENTENDI)

    def _responder_sobre_horarios(
        self, leitura: Leitura, mensagem: MensagemInterpretada, paciente: Paciente, pendente: AcaoPendente
    ) -> ResultadoDialogo | None:
        pergunta = pendente.pergunta
        match leitura.tipo:
            case TipoLeitura.ESCOLHA:
                horario_id = pendente.horarios_oferecidos[leitura.indices[0] - 1]
                return self._escolher(paciente, pendente, horario_id, leitura.automatica)
            case TipoLeitura.AMBIGUA:
                return self._esclarecer(leitura, paciente, pendente)
            case TipoLeitura.OUTRA_OPCAO:
                return self._mais_opcoes(mensagem, paciente, pendente)
            case TipoLeitura.BUSCAR_DIA:
                return self._buscar_no_dia(paciente, pendente, leitura.dia)
            case TipoLeitura.NEGA:
                return self._descartar(paciente, pendente)
            case TipoLeitura.CONFIRMA:
                if pergunta == Pergunta.CONFIRMAR_HORARIO:
                    return self._confirmar_horario(paciente, pendente)
                if pergunta == Pergunta.CONFIRMAR_TROCA:
                    return self.confirmar_troca(paciente, pendente)
                if pergunta in (Pergunta.NOVA_BUSCA, Pergunta.INFORMAR_DESTINO):
                    return self._buscar(paciente, pendente, pendente.criterios)
                # "Sim" diante de uma lista não escolhe silenciosamente o primeiro horário.
                return self.reapresentar(paciente, pendente, Preambulo.ESCOLHA_PENDENTE)
        return None

    def _continuar(
        self, mensagem: MensagemInterpretada, paciente: Paciente, pendente: AcaoPendente
    ) -> ResultadoDialogo | None:
        """Respostas que mudam critérios (outro dia, outra especialidade); nunca gravam."""
        if pendente.tipo == TipoAcao.REMARCAR:
            return self.continue_rescheduling(mensagem, paciente, pendente)
        if pendente.tipo != TipoAcao.AGENDAR:
            return None if mensagem.intencao in _ACOES else self.reapresentar(paciente, pendente, Preambulo.NAO_ENTENDI)
        if mensagem.intencao in (Intencao.CANCELAR, Intencao.REMARCAR, Intencao.LISTAR):
            return None
        language = analyze_scheduling(mensagem.texto)
        novos = criterios_de(mensagem.entidades)
        criterios = self._default_target(pendente.criterios.merge(novos))
        if language.more_options or mensagem.pede_outra_opcao:
            return self._mais_opcoes(mensagem, paciente, pendente)
        if language.availability or language.booking:
            # "Quais dias tem?" não fica preso ao dia sem vagas da mensagem anterior.
            criterios = criterios.model_copy(update={
                "data_inicio": novos.data_inicio, "data_fim": novos.data_fim, "hora": novos.hora, "turno": novos.turno,
            })
            return self._buscar(paciente, pendente, criterios)
        if mensagem.entidades.possui_criterios:
            return self._buscar(paciente, pendente, criterios)
        return self.reapresentar(paciente, pendente, Preambulo.NAO_ENTENDI)

    def _rotear(self, mensagem: MensagemInterpretada, paciente: Paciente) -> ResultadoDialogo:
        match mensagem.intencao:
            case Intencao.REMARCAR:
                return self.start_rescheduling(paciente, origem=mensagem.origem, destino=mensagem.destino)
            case Intencao.AGENDAR:
                return self._agendar_pedido(paciente, criterios_de(mensagem.entidades))
            case Intencao.CANCELAR:
                return self.solicitar_cancelamento(paciente, mensagem.entidades)
            case Intencao.ORIENTACAO_MEDICA:
                return self._recusar_orientacao_medica()
            case Intencao.LISTAR:
                return self._listar(paciente)
            case Intencao.SAUDACAO:
                return ResultadoDialogo(TipoResultado.SAUDACAO)
            case Intencao.AGRADECIMENTO:
                return ResultadoDialogo(TipoResultado.AGRADECIMENTO)
        return ResultadoDialogo(TipoResultado.AJUDA)

    @staticmethod
    def _recusar_orientacao_medica() -> ResultadoDialogo:
        # O sistema não diagnostica nem indica medicamentos: o pedido vira oferta de consulta.
        oferta = AcaoPendente(
            tipo=TipoAcao.AGENDAR,
            origem=TipoResultado.ORIENTACAO_MEDICA_BLOQUEADA,
            criterios=CriteriosAgendamento(especialidade=ESPECIALIDADE_PADRAO),
        )
        return ResultadoDialogo(TipoResultado.ORIENTACAO_MEDICA_BLOQUEADA, acao_pendente=oferta)

    # ---------------------------------------------------------------- busca e escolha
    @staticmethod
    def _default_target(criteria: CriteriosAgendamento) -> CriteriosAgendamento:
        if criteria.possui_alvo:
            return criteria
        return criteria.model_copy(update={"especialidade": ESPECIALIDADE_PADRAO})

    def _agendar_pedido(self, paciente: Paciente, criterios: CriteriosAgendamento) -> ResultadoDialogo:
        if criterios.possui_alvo:
            return self._sugerir_criterios(criterios)
        busca = self._sugerir_criterios(self._default_target(criterios), avisos=(Aviso.ESPECIALIDADE_PADRAO,))
        if busca.tipo != TipoResultado.SEM_PROFISSIONAL or not self.agenda.medicos.list_active():
            return busca
        # Sem clínico geral, mas com outros profissionais, o pedido genérico pergunta a especialidade.
        pergunta = AcaoPendente(tipo=TipoAcao.AGENDAR, origem=TipoResultado.FALTA_ESPECIALIDADE, criterios=criterios)
        return ResultadoDialogo(TipoResultado.FALTA_ESPECIALIDADE, acao_pendente=pergunta)

    def _buscar(self, paciente: Paciente, pendente: AcaoPendente, criterios: CriteriosAgendamento) -> ResultadoDialogo:
        recusados = pendente.recusados if pendente.tipo == TipoAcao.REMARCAR else ()
        return self._no_fluxo(pendente, self._sugerir_criterios(self._default_target(criterios), recusados))

    def _buscar_no_dia(self, paciente: Paciente, pendente: AcaoPendente, dia: date) -> ResultadoDialogo:
        criterios = pendente.criterios.model_copy(update={"data_inicio": dia, "data_fim": dia, "hora": None})
        return self._buscar(paciente, pendente, criterios)

    def _sugerir_criterios(
        self,
        criterios: CriteriosAgendamento,
        recusados: Sequence[int] = (),
        avisos: Sequence[Aviso] = (),
        pedido: CriteriosAgendamento | None = None,
    ) -> ResultadoDialogo:
        medicos, falha = self._resolver_medicos(criterios)
        if falha:
            return falha
        return self._sugerir(medicos, criterios, recusados, avisos, pedido or criterios)

    def _slots(self, medicos: Sequence[Medico], criterios: CriteriosAgendamento, recusados: Sequence[int] = ()):
        return self.agenda.next_available(
            [medico.id for medico in medicos],
            data_inicio=criterios.data_inicio, data_fim=criterios.data_fim,
            hora=criterios.hora, turno=criterios.turno, excluir=recusados, limite=self.page_size,
        )

    def _sugerir(
        self,
        medicos: Sequence[Medico],
        criterios: CriteriosAgendamento,
        recusados: Sequence[int],
        avisos: Sequence[Aviso],
        pedido: CriteriosAgendamento,
    ) -> ResultadoDialogo:
        avisos = list(avisos)
        efetivos = criterios
        slots = self._slots(medicos, efetivos, recusados)
        if not slots and efetivos.hora:
            efetivos = efetivos.without_time()
            slots = self._slots(medicos, efetivos, recusados)
            if slots:
                avisos.append(Aviso.HORARIO_PEDIDO_INDISPONIVEL)
        if not slots and (efetivos.data_inicio or efetivos.data_fim or efetivos.turno):
            # Alternativas fora do período são anunciadas antes da escolha.
            hoje = self.clock.today()
            efetivos = efetivos.model_copy(update={
                "data_inicio": max(hoje, efetivos.data_inicio or hoje), "data_fim": None, "hora": None, "turno": None,
            })
            slots = self._slots(medicos, efetivos, recusados)
            if slots:
                avisos = [aviso for aviso in avisos if aviso != Aviso.HORARIO_PEDIDO_INDISPONIVEL]
                avisos.append(Aviso.FORA_DO_PERIODO)
        avisos = list(dict.fromkeys(avisos))
        especialidade = pedido.especialidade or medicos[0].especialidade
        if not slots:
            sem_vaga = AcaoPendente(
                tipo=TipoAcao.AGENDAR, origem=TipoResultado.SEM_HORARIOS, criterios=pedido, recusados=limitar(recusados)
            )
            mantidos = tuple(aviso for aviso in avisos if aviso in (Aviso.ESPECIALIDADE_PADRAO, Aviso.HORARIO_RESERVADO))
            return ResultadoDialogo(
                TipoResultado.SEM_HORARIOS, especialidade=especialidade, periodo=periodo_de(pedido), pedido=pedido,
                avisos=mantidos, acao_pendente=sem_vaga,
            )
        por_id = {medico.id: medico for medico in medicos}
        opcoes = tuple(OpcaoAgenda.from_horario(slot, por_id[slot.medico_id]) for slot in slots)
        escolhendo = len(opcoes) > 1
        return ResultadoDialogo(
            TipoResultado.SUGESTAO_HORARIO,
            opcao=opcoes[0], opcoes=opcoes, especialidade=especialidade, avisos=tuple(avisos),
            periodo=periodo_de(pedido), pedido=pedido,
            acao_pendente=AcaoPendente(
                tipo=TipoAcao.AGENDAR,
                horario_id=None if escolhendo else opcoes[0].horario_id,
                criterios=efetivos, pedido=pedido, avisos=[str(aviso) for aviso in avisos],
                recusados=limitar(recusados), horarios_oferecidos=[opcao.horario_id for opcao in opcoes],
                aguardando_escolha=escolhendo,
            ),
        )

    def _valid_option(self, slot_id: int | None, criteria: CriteriosAgendamento) -> tuple[Horario, Medico] | None:
        """Não confia em IDs/datas guardados no contexto: confere vaga, médico e critérios no banco."""
        slot = self.agenda.horarios.get_by_id(slot_id) if slot_id else None
        if slot is None or not slot.disponivel or not self.agenda.is_future(slot):
            return None
        doctors, failure = self._resolver_medicos(self._default_target(criteria))
        if failure or slot.medico_id not in {doctor.id for doctor in doctors}:
            return None
        day = date.fromisoformat(slot.data)
        if (criteria.data_inicio and day < criteria.data_inicio) or (criteria.data_fim and day > criteria.data_fim):
            return None
        if criteria.hora and slot.hora_inicio != criteria.hora:
            return None
        if criteria.turno and (bounds := TURNOS.get(criteria.turno)) and not bounds[0] <= slot.hora_inicio < bounds[1]:
            return None
        return slot, next(doctor for doctor in doctors if doctor.id == slot.medico_id)

    def _escolher(
        self, paciente: Paciente, pendente: AcaoPendente, horario_id: int, automatica: bool = False
    ) -> ResultadoDialogo:
        valido = self._valid_option(horario_id, pendente.criterios)
        if valido is None:
            return self._apos_vaga_perdida(pendente, horario_id)
        horario, medico = valido
        avisos = [aviso for aviso in pendente.avisos if aviso in (Aviso.FORA_DO_PERIODO, Aviso.ESPECIALIDADE_PADRAO)]
        if automatica:
            avisos.append(Aviso.ESCOLHA_AUTOMATICA)
        escolhida = pendente.model_copy(update={
            "horario_id": horario.id, "aguardando_escolha": False, "duvida_opcao": None, "duvida_dia": None,
            "avisos": avisos,
        })
        opcao = OpcaoAgenda.from_horario(horario, medico)
        return self._no_fluxo(pendente, ResultadoDialogo(
            TipoResultado.SUGESTAO_HORARIO, opcao=opcao, opcoes=(opcao,), especialidade=medico.especialidade,
            avisos=tuple(Aviso(aviso) for aviso in avisos), pedido=pendente.pedido,
            periodo=periodo_de(pendente.pedido) if pendente.pedido else None, acao_pendente=escolhida,
        ))

    def _esclarecer(self, leitura: Leitura, paciente: Paciente, pendente: AcaoPendente) -> ResultadoDialogo:
        exibidos = self._horarios_exibidos(pendente)
        if leitura.dia is not None:
            indice = leitura.indices[0]
            opcao = exibidos[indice - 1]
            if opcao is None:
                return self._buscar_no_dia(paciente, pendente, leitura.dia)
            # A pergunta passa a ser a escolha: nenhum horário fica pendente de confirmação.
            em_duvida = pendente.model_copy(update={
                "duvida_opcao": indice, "duvida_dia": leitura.dia, "horario_id": None, "aguardando_escolha": True,
            })
            return self._no_fluxo(pendente, ResultadoDialogo(
                TipoResultado.ESCLARECER_OPCAO, opcao=opcao, numero=indice, dia=leitura.dia,
                especialidade=opcao.especialidade, acao_pendente=em_duvida,
            ))
        indices = [indice for indice in leitura.indices if exibidos[indice - 1] is not None]
        opcoes = tuple(exibidos[indice - 1] for indice in indices)
        estreitada = pendente.model_copy(update={
            "horarios_oferecidos": [pendente.horarios_oferecidos[indice - 1] for indice in indices],
            "aguardando_escolha": True, "horario_id": None, "duvida_opcao": None, "duvida_dia": None,
        })
        return self._no_fluxo(pendente, ResultadoDialogo(
            TipoResultado.ESCLARECER_OPCAO, opcao=opcoes[0], opcoes=opcoes,
            especialidade=opcoes[0].especialidade, acao_pendente=estreitada,
        ))

    def _mais_opcoes(
        self, mensagem: MensagemInterpretada | None, paciente: Paciente, pendente: AcaoPendente
    ) -> ResultadoDialogo:
        rejeitados = list(dict.fromkeys([
            *pendente.recusados, *pendente.horarios_oferecidos, *([pendente.horario_id] if pendente.horario_id else []),
        ]))
        criterios = self._default_target(pendente.criterios)
        if len(rejeitados) >= MAX_REJECTIONS:
            return self._no_fluxo(pendente, ResultadoDialogo(
                TipoResultado.SEM_HORARIOS,
                especialidade=criterios.especialidade,
                detalhe="Para continuar a busca, diga um dia ou um período, por exemplo: semana que vem.",
                acao_pendente=AcaoPendente(tipo=TipoAcao.AGENDAR, origem=TipoResultado.SEM_HORARIOS, criterios=criterios),
            ))
        if mensagem is not None and "dia" in normalize_schedule_text(mensagem.texto):
            novos = criterios_de(mensagem.entidades)
            criterios = criterios.model_copy(update={"data_inicio": novos.data_inicio, "data_fim": novos.data_fim})
        busca = self._sugerir_criterios(criterios.without_time(), rejeitados, self._avisos_de_periodo(pendente), pendente.pedido)
        return self._no_fluxo(pendente, busca)

    @staticmethod
    def _avisos_de_periodo(pendente: AcaoPendente) -> tuple[Aviso, ...]:
        """Alternativas de uma busca já ampliada continuam fora do período pedido."""
        return (Aviso.FORA_DO_PERIODO,) if Aviso.FORA_DO_PERIODO in pendente.avisos else ()

    def _apos_vaga_perdida(self, pendente: AcaoPendente, horario_id: int | None) -> ResultadoDialogo:
        """A vaga foi ocupada agora: mostra alternativas e nada é gravado."""
        criterios = self._default_target(pendente.criterios).without_time()
        recusados = [*pendente.recusados, *([horario_id] if horario_id else [])]
        avisos = (Aviso.HORARIO_RESERVADO, *self._avisos_de_periodo(pendente))
        busca = self._sugerir_criterios(criterios, recusados, avisos, pendente.pedido)
        return self._no_fluxo(pendente, busca)

    def _confirmar_horario(self, paciente: Paciente, pendente: AcaoPendente) -> ResultadoDialogo:
        if ja_marcada := self._ja_registrada(paciente, pendente.horario_id):
            return ja_marcada
        valido = self._valid_option(pendente.horario_id, pendente.criterios)
        if valido is None:
            return self._apos_vaga_perdida(pendente, pendente.horario_id)
        # Usa a reserva transacional da aplicação; a disponibilidade é conferida de novo sob bloqueio.
        return self._reservar(valido[0], paciente) or self._apos_vaga_perdida(pendente, pendente.horario_id)

    def _descartar(self, paciente: Paciente, pendente: AcaoPendente) -> ResultadoDialogo:
        if pendente.tipo == TipoAcao.AGENDAR:
            return ResultadoDialogo(TipoResultado.AGENDAMENTO_DESCARTADO)
        return ResultadoDialogo(
            TipoResultado.CANCELAMENTO_DESCARTADO, opcao=self._consulta_do_paciente(paciente, pendente.consulta_id)
        )

    # ---------------------------------------------------------------- reapresentação
    def _etapa_atual(self, paciente: Paciente, pendente: AcaoPendente) -> ResultadoDialogo:
        if pendente.tipo == TipoAcao.RESPONDER_SOLICITACAO:
            notificacao = self._solicitacao_pendente(paciente, pendente.notificacao_id)
            pedido = self._resultado_da_solicitacao(notificacao) if notificacao else None
            return replace(pedido, acao_pendente=pendente) if pedido else ResultadoDialogo(TipoResultado.SAUDACAO)
        if pendente.tipo in (TipoAcao.CANCELAR, TipoAcao.GERENCIAR):
            return self.etapa_de_consulta(paciente, pendente)
        if pendente.tipo == TipoAcao.REMARCAR:
            return self.etapa_de_remarcacao(paciente, pendente)
        return self._etapa_de_agendamento(pendente)

    def _etapa_de_agendamento(self, pendente: AcaoPendente) -> ResultadoDialogo:
        pergunta = pendente.pergunta
        avisos = tuple(Aviso(aviso) for aviso in pendente.avisos)
        periodo = periodo_de(pendente.pedido) if pendente.pedido else None
        if pergunta in (Pergunta.NOVA_BUSCA, Pergunta.INFORMAR_DESTINO):
            if pendente.origem in (
                TipoResultado.ORIENTACAO_MEDICA_BLOQUEADA, TipoResultado.SEM_PROFISSIONAL, TipoResultado.FALTA_ESPECIALIDADE
            ):
                especialidade = pendente.pedido.especialidade if pendente.pedido else None
                return ResultadoDialogo(
                    TipoResultado(pendente.origem), especialidade=especialidade, acao_pendente=pendente
                )
            return self._no_fluxo(pendente, self._sugerir_criterios(self._default_target(pendente.criterios), pendente.recusados))
        exibidos = self._horarios_exibidos(pendente)
        em_duvida = pendente.duvida_opcao if pendente.duvida_opcao and pendente.duvida_opcao <= len(exibidos) else None
        if pendente.duvida_dia and em_duvida and (opcao := exibidos[em_duvida - 1]):
            return ResultadoDialogo(
                TipoResultado.ESCLARECER_OPCAO, opcao=opcao, numero=pendente.duvida_opcao, dia=pendente.duvida_dia,
                especialidade=opcao.especialidade, acao_pendente=pendente,
            )
        if pergunta in (Pergunta.CONFIRMAR_HORARIO, Pergunta.CONFIRMAR_TROCA):
            valido = self._valid_option(pendente.horario_id, pendente.criterios)
            if valido is None:
                return self._apos_vaga_perdida(pendente, pendente.horario_id)
            opcao = OpcaoAgenda.from_horario(*valido)
            return ResultadoDialogo(
                TipoResultado.SUGESTAO_HORARIO, opcao=opcao, opcoes=(opcao,), especialidade=opcao.especialidade,
                avisos=avisos, periodo=periodo, pedido=pendente.pedido, acao_pendente=pendente,
            )
        livres = [
            (horario_id, opcao) for horario_id, opcao in zip(pendente.horarios_oferecidos, exibidos)
            if opcao is not None and self._valid_option(horario_id, pendente.criterios)
        ]
        if not livres:
            recusados = [*pendente.recusados, *pendente.horarios_oferecidos]
            busca = self._sugerir_criterios(
                self._default_target(pendente.criterios), recusados,
                (Aviso.HORARIO_RESERVADO, *self._avisos_de_periodo(pendente)), pendente.pedido,
            )
            return self._no_fluxo(pendente, busca)
        atual = pendente
        if len(livres) < len(pendente.horarios_oferecidos):
            avisos = tuple(dict.fromkeys((*avisos, Aviso.OPCOES_REDUZIDAS)))
        if [horario_id for horario_id, _ in livres] != pendente.horarios_oferecidos:
            atual = pendente.model_copy(update={
                "horarios_oferecidos": [horario_id for horario_id, _ in livres],
                "aguardando_escolha": len(livres) > 1,
                "horario_id": None if len(livres) > 1 else livres[0][0],
                "avisos": [str(aviso) for aviso in avisos],
            })
        opcoes = tuple(opcao for _, opcao in livres)
        return ResultadoDialogo(
            TipoResultado.SUGESTAO_HORARIO, opcao=opcoes[0], opcoes=opcoes, especialidade=opcoes[0].especialidade,
            avisos=avisos, periodo=periodo, pedido=pendente.pedido, acao_pendente=atual,
        )

    def _horarios_exibidos(self, pendente: AcaoPendente) -> list[OpcaoAgenda | None]:
        if pendente.pergunta not in _PERGUNTAS_SOBRE_HORARIOS:
            return []
        return [self._opcao_do_horario(horario_id) for horario_id in pendente.horarios_oferecidos]

    def _opcao_do_horario(self, horario_id: int) -> OpcaoAgenda | None:
        horario = self.agenda.horarios.get_by_id(horario_id)
        medico = self.db.get(Medico, horario.medico_id) if horario else None
        return OpcaoAgenda.from_horario(horario, medico) if medico else None

    def _consultas_exibidas(self, paciente: Paciente, pendente: AcaoPendente) -> list[OpcaoAgenda | None]:
        por_id = {opcao.consulta_id: opcao for opcao in self._consultas_futuras(paciente)}
        return [por_id.get(consulta_id) for consulta_id in pendente.consultas_oferecidas]
