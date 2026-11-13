"""Remarcação conversacional: seleciona origem, destino, confirma e transfere."""
from dataclasses import replace

from app.backend.assistant.dialogue import OpcaoAgenda, ResultadoDialogo, TipoResultado, criterios_de
from app.backend.assistant.nlp import Intencao
from app.backend.assistant.scheduling_language import analyze_scheduling
from app.backend.core.exceptions import DomainError
from app.backend.models import StatusConsulta
from app.backend.schemas.assistant import AcaoPendente, CriteriosAgendamento, TipoAcao


class AtomicRescheduling:
    def start_rescheduling(self, patient, page=0):
        options = self._consultas_futuras(patient)
        if not options:
            return ResultadoDialogo(TipoResultado.SEM_CONSULTAS)
        if len(options) == 1:
            return self._request_destination(patient, options[0].consulta_id)
        batch = options[page:page + self.page_size]
        if not batch:
            page, batch = 0, options[:self.page_size]
        return ResultadoDialogo(
            TipoResultado.ORIENTAR_REMARCACAO, opcoes=tuple(batch),
            acao_pendente=AcaoPendente(tipo=TipoAcao.REMARCAR, etapa_remarcacao="origem",
                                      consultas_oferecidas=[option.consulta_id for option in batch], pagina_consultas=page),
        )

    def _owned_consultation(self, patient, consultation_id):
        consultation = self.consultas_repository.get_by_id(consultation_id) if consultation_id else None
        if consultation is None or consultation.paciente_id != patient.id or consultation.status != StatusConsulta.AGENDADA:
            return None
        return consultation

    def _request_destination(self, patient, consultation_id):
        consultation = self._owned_consultation(patient, consultation_id)
        if consultation is None:
            return ResultadoDialogo(TipoResultado.CONSULTA_NAO_ENCONTRADA)
        detail = self._detalhar(consultation.id)
        option = OpcaoAgenda.from_consulta(detail, consultation.horario_id)
        return ResultadoDialogo(
            TipoResultado.ORIENTAR_REMARCACAO, opcao=option,
            acao_pendente=AcaoPendente(tipo=TipoAcao.REMARCAR, consulta_id=consultation.id,
                origem_horario_id=consultation.horario_id, etapa_remarcacao="destino",
                criterios=CriteriosAgendamento(medico_nome=detail.medico_nome, especialidade=detail.especialidade)),
        )

    def continue_rescheduling(self, message, patient, pending):
        if message.intencao in (Intencao.LISTAR, Intencao.CANCELAR, Intencao.ORIENTACAO_MEDICA):
            return None
        language = analyze_scheduling(message.texto)
        if message.negativa and not message.entidades.possui_criterios:
            return ResultadoDialogo(TipoResultado.CANCELAMENTO_DESCARTADO)
        if pending.etapa_remarcacao == "origem":
            if language.more_options or "mais consultas" in message.texto.lower():
                return self.start_rescheduling(patient, pending.pagina_consultas + len(pending.consultas_oferecidas))
            if language.option and 1 <= language.option <= len(pending.consultas_oferecidas):
                return self._request_destination(patient, pending.consultas_oferecidas[language.option - 1])
            matches = self._filtrar(self._consultas_futuras(patient), message.entidades)
            if message.entidades.possui_criterios and len(matches) == 1:
                return self._request_destination(patient, matches[0].consulta_id)
            return self.start_rescheduling(patient, pending.pagina_consultas)
        consultation = self._owned_consultation(patient, pending.consulta_id)
        if consultation is None:
            return ResultadoDialogo(TipoResultado.CONSULTA_NAO_ENCONTRADA)
        if consultation.horario_id != pending.origem_horario_id:
            return self._request_destination(patient, consultation.id)
        if pending.horario_id and not pending.aguardando_escolha and message.afirmativa and not message.entidades.possui_criterios:
            if self._valid_option(pending.horario_id, pending.criterios) is None:
                result = self._sugerir_criterios(pending.criterios.without_time(), [*pending.recusados, pending.horario_id])
            else:
                try:
                    changed = self.consultas.reschedule_for_patient(
                        consultation.id, patient.id, pending.horario_id, pending.origem_horario_id,
                    )
                except DomainError as exc:
                    return ResultadoDialogo(TipoResultado.REGRA_VIOLADA, detalhe=exc.detail)
                detail = self._detalhar(changed.id)
                return ResultadoDialogo(TipoResultado.REMARCACAO_ACEITA, consulta=detail, opcao=OpcaoAgenda.from_consulta(detail, pending.horario_id))
        elif not pending.horarios_oferecidos and pending.horario_id is None:
            criteria = pending.criterios.merge(criterios_de(message.entidades))
            result = self._agendar(patient, criteria, [pending.origem_horario_id])
        else:
            # A confirmação é interceptada acima; aqui a delegação somente lista/seleciona vagas.
            temporary = pending.model_copy(update={"tipo": TipoAcao.AGENDAR})
            result = self._continuar(message, patient, temporary)
            if result is None:
                result = self._agendar(patient, temporary.criterios, temporary.recusados)
        if result.acao_pendente:
            result = replace(result, acao_pendente=result.acao_pendente.model_copy(update={
                "tipo": TipoAcao.REMARCAR, "consulta_id": pending.consulta_id,
                "origem_horario_id": pending.origem_horario_id, "etapa_remarcacao": "destino",
            }))
        return result
