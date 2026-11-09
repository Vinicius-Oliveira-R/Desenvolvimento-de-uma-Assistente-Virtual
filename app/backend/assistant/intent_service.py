import re
from dataclasses import dataclass
from datetime import date
from typing import Any

from sqlalchemy.orm import Session

from app.backend.assistant.nlp import Intencao, MessageInterpreter, get_language_processor
from app.backend.assistant.temporal import TemporalResolver
from app.backend.core.clock import Clock
from app.backend.core.exceptions import BusinessRuleError, NotFoundError
from app.backend.models import Horario, Medico, Paciente
from app.backend.repositories.paciente_repository import PacienteRepository
from app.backend.schemas.consulta import ConsultaCreate, ConsultaOut
from app.backend.services.agenda_service import AgendaService
from app.backend.services.consulta_service import ConsultaService


@dataclass(frozen=True)
class _PedidoAgendamento:
    medico_citado: str | None
    medico: Medico | None
    paciente_citado: str | None
    paciente: Paciente | None
    data: date | None
    hora: str | None
    horario: Horario | None


class AssistantIntentService:
    def __init__(self, db: Session, clock: Clock):
        self.db = db
        self.interpreter = MessageInterpreter(get_language_processor(), TemporalResolver(clock))
        self.agenda = AgendaService(db, clock)
        self.pacientes = PacienteRepository(db)

    @staticmethod
    def _normalize_text(value: str) -> str:
        return re.sub(r"\s+", " ", value.strip().lower())

    def interpret(self, mensagem: str) -> dict[str, Any]:
        pedido = self._analisar(mensagem)
        return {
            "intent": "agendar_consulta",
            "doctor": pedido.medico.nome if pedido.medico else pedido.medico_citado,
            "data": pedido.data.isoformat() if pedido.data else None,
            "hora": pedido.hora,
            "patient": pedido.paciente.nome if pedido.paciente else pedido.paciente_citado,
            "status": "slot_disponivel" if pedido.horario and pedido.horario.disponivel else "slot_indisponivel",
            "slot_id": pedido.horario.id if pedido.horario else None,
        }

    def schedule_from_message(self, mensagem: str) -> ConsultaOut:
        pedido = self._analisar(mensagem)
        if not (pedido.medico and pedido.paciente and pedido.data and pedido.hora):
            raise BusinessRuleError("Mensagem incompleta para agendamento")
        if pedido.horario is None:
            raise NotFoundError("Horário não encontrado")

        return ConsultaService(self.db).create(
            ConsultaCreate(
                paciente_id=pedido.paciente.id,
                medico_id=pedido.medico.id,
                horario_id=pedido.horario.id,
                data=pedido.horario.data,
                observacao="Agendamento realizado pelo assistente",
            )
        )

    def recommend_best_slot(self, mensagem: str) -> dict[str, Any]:
        especialidade = self.interpreter.interpret(mensagem).entidades.especialidade
        if not especialidade:
            raise BusinessRuleError("Especialidade não identificada")

        medicos = self.agenda.find_doctors_by_specialty(especialidade)
        horarios = self.agenda.next_available([medico.id for medico in medicos]) if medicos else []
        if not horarios:
            raise NotFoundError("Nenhum horário disponível encontrado")

        horario = horarios[0]
        medico = next(medico for medico in medicos if medico.id == horario.medico_id)
        return {
            "especialidade": medico.especialidade,
            "medico": medico.nome,
            "data": horario.data,
            "hora": horario.hora_inicio,
            "mensagem": f"Sugestão: {medico.nome} - {medico.especialidade} - {horario.data} às {horario.hora_inicio}.",
        }

    def _analisar(self, mensagem: str) -> _PedidoAgendamento:
        interpretacao = self.interpreter.interpret(mensagem)
        if interpretacao.intencao != Intencao.AGENDAR:
            raise BusinessRuleError("Intenção não reconhecida")

        entidades = interpretacao.entidades
        medico = self._localizar_medico(entidades.medico)
        paciente_citado = self._extract_patient_name(self._normalize_text(mensagem))
        paciente = self._localizar_paciente(paciente_citado)
        horario = (
            self.agenda.find_slot(medico.id, entidades.data, entidades.hora)
            if medico and entidades.data and entidades.hora
            else None
        )
        return _PedidoAgendamento(
            entidades.medico, medico, paciente_citado, paciente, entidades.data, entidades.hora, horario
        )

    def _localizar_medico(self, nome: str | None) -> Medico | None:
        if not nome:
            return None
        encontrados = self.agenda.find_doctors_by_name(nome)
        if not encontrados:
            raise NotFoundError("Médico não encontrado")
        return encontrados[0]

    def _localizar_paciente(self, nome: str | None) -> Paciente | None:
        if not nome:
            return None
        paciente = self.pacientes.find_by_name(nome)
        if not paciente:
            raise NotFoundError("Paciente não encontrado")
        return paciente

    @staticmethod
    def _extract_patient_name(text: str) -> str | None:
        for pattern in [
            r"(?:paciente|para o paciente)\s+([a-zà-úçãõéíóú\s]+?)(?:$|\s+com\s+|\s+para\s+\d{4}|\s+para\s+\d{2}:\d{2})",
            r"(?:para)\s+([a-zà-úçãõéíóú\s]+?)(?:$|\s+com\s+|\s+para\s+\d{4}|\s+para\s+\d{2}:\d{2})",
        ]:
            match = re.search(pattern, text)
            if match:
                value = match.group(1).strip()
                if value:
                    return value
        return None
