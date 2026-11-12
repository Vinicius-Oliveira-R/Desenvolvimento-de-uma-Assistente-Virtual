"""Agenda conversacional: listar -> escolher -> confirmar -> reservar.

Os horários vêm de AgendaService. O serviço de consulta existente continua
responsável pela transação e por impedir que duas pessoas reservem a mesma vaga.
"""

from collections.abc import Sequence
from dataclasses import replace
from datetime import date

from app.backend.assistant.dialogue import (
    Aviso, DialogueManager, OpcaoAgenda, ResultadoDialogo, TipoResultado, criterios_de,
)
from app.backend.assistant.especialidades import ESPECIALIDADE_PADRAO
from app.backend.assistant.nlp import Intencao, MessageInterpreter, MensagemInterpretada
from app.backend.assistant.scheduling_language import analyze_scheduling, normalize_schedule_text
from app.backend.assistant.temporal import IntervaloDatas, TURNOS
from app.backend.models import Horario, Medico, Paciente
from app.backend.schemas.assistant import AcaoPendente, CriteriosAgendamento, TipoAcao

PAGE_SIZE = 6
MAX_REJECTIONS = 120


class SchedulingMessageInterpreter(MessageInterpreter):
    """Acrescenta linguagem de agenda sem substituir as entidades do spaCy."""

    def interpret(self, texto: str) -> MensagemInterpretada:
        message = super().interpret(texto)
        language = analyze_scheduling(texto)
        # Não converte cancelamento, remarcação ou orientação médica em marcação.
        if message.intencao in (Intencao.CANCELAR, Intencao.REMARCAR, Intencao.ORIENTACAO_MEDICA):
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


class SchedulingDialogueManager(DialogueManager):
    """Mantém os fluxos existentes de consultas/notificações e melhora a agenda."""

    @staticmethod
    def _default_target(criteria: CriteriosAgendamento) -> CriteriosAgendamento:
        if criteria.possui_alvo:
            return criteria
        return criteria.model_copy(update={"especialidade": ESPECIALIDADE_PADRAO})

    def _rotear(self, mensagem: MensagemInterpretada, paciente: Paciente) -> ResultadoDialogo:
        if mensagem.intencao == Intencao.AGENDAR:
            criteria = criterios_de(mensagem.entidades)
            defaulted = not criteria.possui_alvo
            result = self._agendar(paciente, self._default_target(criteria))
            if defaulted and result.tipo == TipoResultado.SUGESTAO_HORARIO:
                note = "Como você não indicou uma especialidade, busquei Clínica Geral."
                return replace(result, detalhe=f"{note}\n{result.detalhe or ''}".strip())
            return result
        return super()._rotear(mensagem, paciente)

    def _continuar(self, mensagem: MensagemInterpretada, paciente: Paciente, pendente: AcaoPendente):
        if pendente.tipo != TipoAcao.AGENDAR:
            return super()._continuar(mensagem, paciente, pendente)
        if mensagem.intencao in (
            Intencao.CANCELAR, Intencao.REMARCAR, Intencao.LISTAR, Intencao.ORIENTACAO_MEDICA,
        ):
            return None

        language = analyze_scheduling(mensagem.texto)
        new = criterios_de(mensagem.entidades)
        criteria = self._default_target(pendente.criterios.merge(new))

        if language.more_options or mensagem.pede_outra_opcao:
            rejected = list(dict.fromkeys([
                *pendente.recusados, *pendente.horarios_oferecidos,
                *([pendente.horario_id] if pendente.horario_id else []),
            ]))
            if len(rejected) >= MAX_REJECTIONS:
                return ResultadoDialogo(
                    TipoResultado.SEM_HORARIOS,
                    especialidade=criteria.especialidade,
                    detalhe="Para continuar a busca, diga um dia ou um período, por exemplo: semana que vem.",
                    acao_pendente=AcaoPendente(tipo=TipoAcao.AGENDAR, criterios=criteria),
                )
            if "dia" in normalize_schedule_text(mensagem.texto):
                criteria = criteria.model_copy(update={"data_inicio": new.data_inicio, "data_fim": new.data_fim})
            return self._sugerir_criterios(criteria.without_time(), rejected)

        if pendente.aguardando_escolha and language.option is not None:
            if 1 <= language.option <= len(pendente.horarios_oferecidos):
                return self._choose(
                    pendente.horarios_oferecidos[language.option - 1], paciente, pendente.criterios, pendente.recusados,
                )
            result = self._agendar(paciente, criteria, pendente.recusados)
            return replace(result, detalhe="Escolha um dos números da lista abaixo. Nenhuma consulta foi marcada.")

        if language.availability or language.booking:
            # "Quais dias tem?" não deve ficar preso ao dia sem vagas da mensagem anterior.
            # Um alvo explicitamente escolhido é preservado; data/turno novos são respeitados.
            criteria = criteria.model_copy(update={
                "data_inicio": new.data_inicio, "data_fim": new.data_fim,
                "hora": new.hora, "turno": new.turno,
            })
            return self._agendar(paciente, criteria)

        if language.no_preference or mensagem.sem_preferencia:
            return self._agendar(paciente, criteria)

        if pendente.aguardando_escolha:
            if mensagem.negativa and not mensagem.entidades.possui_criterios:
                return ResultadoDialogo(TipoResultado.AGENDAMENTO_DESCARTADO)
            if mensagem.entidades.possui_criterios:
                # Data/hora podem identificar uma opção, mas nunca reservam sem confirmação.
                matches = [
                    slot_id for slot_id in pendente.horarios_oferecidos
                    if self._valid_option(slot_id, criteria) is not None
                ]
                if len(matches) == 1:
                    return self._choose(matches[0], paciente, criteria, pendente.recusados)
                return self._agendar(paciente, criteria)
            # "Sim" não escolhe silenciosamente o primeiro de vários horários.
            result = self._agendar(paciente, criteria, pendente.recusados)
            return replace(result, detalhe="Qual opção você prefere? Responda com o número ou com o dia e a hora.")

        if mensagem.intencao == Intencao.DESCONHECIDA and not mensagem.entidades.possui_criterios:
            result = self._agendar(paciente, criteria, pendente.recusados)
            return replace(result, detalhe="Vamos continuar com a agenda. Escolha um horário abaixo ou diga outro dia.")
        return super()._continuar(mensagem, paciente, pendente)

    def _agendar(self, paciente: Paciente, criterios: CriteriosAgendamento, recusados: Sequence[int] = ()):
        # Inclusive pedidos exatos de data/hora aguardam confirmação explícita.
        return self._sugerir_criterios(self._default_target(criterios), recusados)

    def _sugerir_criterios(self, criteria: CriteriosAgendamento, rejected: Sequence[int] = ()):
        doctors, failure = self._resolver_medicos(criteria)
        if failure:
            if failure.tipo == TipoResultado.SEM_HORARIOS:
                return replace(
                    failure,
                    detalhe="Não encontrei um médico cadastrado nessa especialidade. Fale com a recepção da clínica.",
                )
            return failure
        return self._sugerir(doctors, criteria, rejected)

    def _slots(self, doctors, criteria, rejected=()):
        return self.agenda.next_available(
            [doctor.id for doctor in doctors],
            data_inicio=criteria.data_inicio, data_fim=criteria.data_fim,
            hora=criteria.hora, turno=criteria.turno, excluir=rejected, limite=PAGE_SIZE,
        )

    def _sugerir(self, medicos: Sequence[Medico], criterios: CriteriosAgendamento, recusados: Sequence[int], aviso=None):
        slots = self._slots(medicos, criterios, recusados)
        note = None
        effective = criterios
        if not slots and criterios.hora:
            effective = criterios.without_time()
            slots = self._slots(medicos, effective, recusados)
            if slots:
                aviso = aviso or Aviso.HORARIO_PEDIDO_INDISPONIVEL
        if not slots and (effective.data_inicio or effective.data_fim or effective.turno):
            # Alternativas são explicitamente apresentadas como fora do período solicitado.
            after = max(self.clock.today(), effective.data_inicio or self.clock.today())
            effective = effective.model_copy(update={"data_inicio": after, "data_fim": None, "hora": None, "turno": None})
            slots = self._slots(medicos, effective, recusados)
            if slots:
                note = "Não há vaga no dia ou período pedido. Encontrei estas alternativas a partir dessa data:"
        if not slots:
            return ResultadoDialogo(
                TipoResultado.SEM_HORARIOS,
                especialidade=criterios.especialidade or medicos[0].especialidade,
                periodo=IntervaloDatas(criterios.data_inicio, criterios.data_fim or criterios.data_inicio) if criterios.data_inicio else None,
                detalhe="Não encontrei horários livres na busca. A recepção pode informar sobre a liberação de novas vagas. Não marquei nenhuma consulta.",
                acao_pendente=AcaoPendente(tipo=TipoAcao.AGENDAR, criterios=criterios, recusados=list(recusados)),
            )
        by_id = {doctor.id: doctor for doctor in medicos}
        options = tuple(OpcaoAgenda.from_horario(slot, by_id[slot.medico_id]) for slot in slots)
        choosing = len(options) > 1
        return ResultadoDialogo(
            TipoResultado.SUGESTAO_HORARIO,
            opcao=options[0], opcoes=options,
            especialidade=effective.especialidade or options[0].especialidade,
            aviso=aviso, detalhe=note,
            acao_pendente=AcaoPendente(
                tipo=TipoAcao.AGENDAR,
                horario_id=None if choosing else options[0].horario_id,
                criterios=effective, recusados=list(recusados),
                horarios_oferecidos=[option.horario_id for option in options], aguardando_escolha=choosing,
            ),
        )

    def _valid_option(self, slot_id: int, criteria: CriteriosAgendamento):
        """Não confia em IDs/datas enviados no contexto do navegador."""
        slot = self.agenda.horarios.get_by_id(slot_id)
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

    def _choose(self, slot_id, paciente, criteria, rejected=()):
        valid = self._valid_option(slot_id, criteria)
        if not valid:
            result = self._agendar(paciente, criteria.without_time(), [*rejected, slot_id])
            return replace(result, detalhe="Essa opção não está mais disponível. Confira as alternativas atuais; nada foi marcado.")
        slot, doctor = valid
        chosen = criteria.model_copy(update={
            "medico_nome": doctor.nome, "especialidade": doctor.especialidade,
            "data_inicio": date.fromisoformat(slot.data), "data_fim": date.fromisoformat(slot.data),
            "hora": slot.hora_inicio,
        })
        return ResultadoDialogo(
            TipoResultado.SUGESTAO_HORARIO,
            opcao=OpcaoAgenda.from_horario(slot, doctor),
            detalhe="Você escolheu esta opção. A consulta ainda não foi marcada.",
            acao_pendente=AcaoPendente(tipo=TipoAcao.AGENDAR, horario_id=slot.id, criterios=chosen, recusados=list(rejected)),
        )

    def _executar(self, pendente, paciente):
        if pendente.tipo != TipoAcao.AGENDAR:
            return super()._executar(pendente, paciente)
        if pendente.aguardando_escolha or pendente.horario_id is None:
            return self._agendar(paciente, pendente.criterios, pendente.recusados)
        valid = self._valid_option(pendente.horario_id, pendente.criterios)
        if not valid:
            return self._choose(pendente.horario_id, paciente, pendente.criterios, pendente.recusados)
        # Usa a mesma reserva transacional da aplicação; disponibilidade é conferida novamente nela.
        return self._reservar(valid[0], paciente, pendente.criterios, pendente.recusados)
