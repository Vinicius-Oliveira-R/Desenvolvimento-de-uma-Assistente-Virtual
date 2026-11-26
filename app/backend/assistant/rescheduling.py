"""Remarcação conversacional: seleciona origem, destino, confirma e transfere de forma atômica.

A consulta atual só muda depois da confirmação. Se a vaga de destino for ocupada antes
ou durante a transferência, a transação é desfeita e a consulta original continua marcada.
"""
from dataclasses import replace

from app.backend.assistant.dialogue import (
    OpcaoAgenda,
    Preambulo,
    ResultadoDialogo,
    TipoResultado,
    criterios_de,
    limitar,
)
from app.backend.assistant.nlp import Entidades, Intencao
from app.backend.assistant.scheduling_language import analyze_scheduling
from app.backend.core.exceptions import DomainError, HorarioIndisponivelError
from app.backend.models import StatusConsulta
from app.backend.schemas.assistant import AcaoPendente, CriteriosAgendamento, Pergunta, TipoAcao


class AtomicRescheduling:
    def start_rescheduling(
        self, patient, page: int = 0, origem: Entidades | None = None, destino: Entidades | None = None
    ) -> ResultadoDialogo:
        options = self._consultas_futuras(patient)
        if not options:
            return ResultadoDialogo(TipoResultado.SEM_CONSULTAS)
        candidates = options
        if origem is not None and origem.possui_criterios:
            candidates = self._filtrar(options, origem)
            if not candidates and destino is None:
                # "Remarcar para dia 12": sem consulta nesse dia, a data descreve o destino.
                candidates, destino = options, origem
            candidates = candidates or options
        preferencias = criterios_de(destino) if destino is not None else CriteriosAgendamento()
        if len(candidates) == 1:
            return self._request_destination(patient, candidates[0].consulta_id, preferencias)
        batch = candidates[page:page + self.page_size]
        if not batch:
            page, batch = 0, candidates[:self.page_size]
        return ResultadoDialogo(
            TipoResultado.ORIENTAR_REMARCACAO, opcoes=tuple(batch),
            acao_pendente=AcaoPendente(
                tipo=TipoAcao.REMARCAR, etapa_remarcacao="origem", criterios=preferencias,
                consultas_oferecidas=[option.consulta_id for option in batch], pagina_consultas=page,
            ),
        )

    def _owned_consultation(self, patient, consultation_id):
        consultation = self.consultas_repository.get_by_id(consultation_id) if consultation_id else None
        if consultation is None or consultation.paciente_id != patient.id or consultation.status != StatusConsulta.AGENDADA:
            return None
        return consultation

    def _request_destination(self, patient, consultation_id, preferencias: CriteriosAgendamento | None = None):
        consultation = self._owned_consultation(patient, consultation_id)
        if consultation is None:
            return ResultadoDialogo(TipoResultado.CONSULTA_NAO_ENCONTRADA)
        detail = self._detalhar(consultation.id)
        option = OpcaoAgenda.from_consulta(detail, consultation.horario_id)
        pending = AcaoPendente(
            tipo=TipoAcao.REMARCAR, consulta_id=consultation.id, origem_horario_id=consultation.horario_id,
            etapa_remarcacao="destino", recusados=[consultation.horario_id],
            criterios=CriteriosAgendamento(medico_nome=detail.medico_nome, especialidade=detail.especialidade),
        )
        preferencias = preferencias or CriteriosAgendamento()
        if preferencias.data_inicio or preferencias.hora or preferencias.turno or preferencias.possui_alvo:
            # Um pedido completo ("de sexta para segunda à tarde") já busca o destino.
            return self._buscar(patient, pending, pending.criterios.merge(preferencias))
        return ResultadoDialogo(
            TipoResultado.ORIENTAR_REMARCACAO, opcao=option, consulta_atual=option, acao_pendente=pending
        )

    def continue_rescheduling(self, message, patient, pending: AcaoPendente) -> ResultadoDialogo | None:
        if message.intencao in (Intencao.LISTAR, Intencao.CANCELAR):
            return None
        language = analyze_scheduling(message.texto)
        if pending.etapa_remarcacao == "origem":
            if language.more_options or "mais consultas" in message.texto.lower():
                return self.start_rescheduling(patient, pending.pagina_consultas + len(pending.consultas_oferecidas))
            if message.entidades.possui_criterios:
                matches = self._filtrar(self._consultas_futuras(patient), message.entidades)
                if len(matches) == 1:
                    return self._request_destination(patient, matches[0].consulta_id, pending.criterios)
            if message.intencao == Intencao.REMARCAR:
                return None
            return self.reapresentar(patient, pending, Preambulo.NAO_ENTENDI)
        consultation = self._owned_consultation(patient, pending.consulta_id)
        if consultation is None:
            return ResultadoDialogo(TipoResultado.CONSULTA_NAO_ENCONTRADA)
        if consultation.horario_id != pending.origem_horario_id:
            return self._request_destination(patient, consultation.id)
        if language.more_options or message.pede_outra_opcao:
            return self._mais_opcoes(message, patient, pending)
        new = criterios_de(message.entidades)
        if message.entidades.possui_criterios or language.availability:
            criteria = pending.criterios.merge(new)
            if language.availability and not message.entidades.possui_criterios:
                criteria = criteria.model_copy(update={"data_inicio": None, "data_fim": None, "hora": None, "turno": None})
            return self._buscar(patient, pending, criteria)
        if message.intencao == Intencao.REMARCAR:
            return None
        return self.reapresentar(patient, pending, Preambulo.NAO_ENTENDI)

    def confirmar_troca(self, patient, pending: AcaoPendente) -> ResultadoDialogo:
        """Confere titularidade, estado, origem e destino antes da transferência atômica."""
        consultation = self._owned_consultation(patient, pending.consulta_id)
        if consultation is None:
            return ResultadoDialogo(TipoResultado.CONSULTA_NAO_ENCONTRADA)
        origem = self._opcao_do_horario(pending.origem_horario_id)
        if consultation.horario_id == pending.horario_id:
            # Clique duplo ou repetição após queda de conexão: a troca já está registrada.
            return replace(self._troca_registrada(consultation.id, origem), preambulo=Preambulo.JA_REGISTRADA)
        if consultation.horario_id != pending.origem_horario_id:
            return self._request_destination(patient, consultation.id)
        if self._valid_option(pending.horario_id, pending.criterios) is None:
            return self._apos_vaga_perdida(pending, pending.horario_id)
        try:
            changed = self.consultas.reschedule_for_patient(
                consultation.id, patient.id, pending.horario_id, pending.origem_horario_id,
            )
        except HorarioIndisponivelError:
            return self._apos_vaga_perdida(pending, pending.horario_id)
        except DomainError as exc:
            return ResultadoDialogo(TipoResultado.REGRA_VIOLADA, detalhe=exc.detail)
        return self._troca_registrada(changed.id, origem)

    def _troca_registrada(self, consulta_id: int, origem: OpcaoAgenda | None) -> ResultadoDialogo:
        detail = self._detalhar(consulta_id)
        consulta = self.consultas_repository.get_by_id(consulta_id)
        return ResultadoDialogo(
            TipoResultado.REMARCACAO_ACEITA, consulta=detail, consulta_atual=origem,
            opcao=OpcaoAgenda.from_consulta(detail, consulta.horario_id),
        )

    def etapa_de_remarcacao(self, patient, pending: AcaoPendente) -> ResultadoDialogo:
        if pending.etapa_remarcacao == "origem":
            exibidas = [opcao for opcao in self._consultas_exibidas(patient, pending) if opcao is not None]
            if not exibidas:
                return self.start_rescheduling(patient)
            atual = pending.model_copy(update={"consultas_oferecidas": [opcao.consulta_id for opcao in exibidas]})
            return ResultadoDialogo(TipoResultado.ORIENTAR_REMARCACAO, opcoes=tuple(exibidas), acao_pendente=atual)
        consultation = self._owned_consultation(patient, pending.consulta_id)
        if consultation is None:
            return ResultadoDialogo(TipoResultado.CONSULTA_NAO_ENCONTRADA)
        if consultation.horario_id != pending.origem_horario_id:
            return self._request_destination(patient, consultation.id)
        if pending.pergunta == Pergunta.INFORMAR_DESTINO and pending.origem is None:
            atual = self._opcao_atual(pending)
            return ResultadoDialogo(
                TipoResultado.ORIENTAR_REMARCACAO, opcao=atual, consulta_atual=atual, acao_pendente=pending
            )
        return self._no_fluxo(pending, self._etapa_de_agendamento(pending))

    def _no_fluxo(self, pending: AcaoPendente, result: ResultadoDialogo) -> ResultadoDialogo:
        """Mantém a busca de vagas dentro da remarcação, com a consulta atual sempre visível."""
        if pending.tipo != TipoAcao.REMARCAR:
            return result
        moved = result.acao_pendente
        if moved is not None and moved.tipo != TipoAcao.REMARCAR:
            moved = moved.model_copy(update={
                "tipo": TipoAcao.REMARCAR, "consulta_id": pending.consulta_id,
                "origem_horario_id": pending.origem_horario_id, "etapa_remarcacao": "destino",
                "recusados": limitar(moved.recusados, manter=pending.origem_horario_id),
            })
        return replace(result, acao_pendente=moved, consulta_atual=self._opcao_atual(pending))

    def _opcao_atual(self, pending: AcaoPendente) -> OpcaoAgenda | None:
        return self._opcao_do_horario(pending.origem_horario_id) if pending.origem_horario_id else None
