import re
from typing import Any

from fastapi import HTTPException, status
from sqlalchemy.orm import Session

from app.backend.models import Horario, Medico, Paciente
from app.backend.schemas.consulta import ConsultaCreate
from app.backend.services.consulta_service import ConsultaService


class AssistantIntentService:
    def __init__(self, db: Session):
        self.db = db

    @staticmethod
    def _normalize_text(value: str) -> str:
        return re.sub(r"\s+", " ", value.strip().lower())

    def interpret(self, mensagem: str) -> dict[str, Any]:
        text = self._normalize_text(mensagem)

        intent = "agendar_consulta" if "agendar" in text or "consulta" in text else "desconhecida"

        doctor_name = self._extract_doctor_name(text)
        data = self._extract_date(text)
        hora = self._extract_time(text)
        patient_name = self._extract_patient_name(text)

        if intent == "desconhecida":
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Intenção não reconhecida")

        doctor = self.db.query(Medico).filter(Medico.nome.ilike(f"%{doctor_name}%")).first() if doctor_name else None
        if doctor_name and not doctor:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Médico não encontrado")

        patient = (
            self.db.query(Paciente).filter(Paciente.nome.ilike(f"%{patient_name}%")).first() if patient_name else None
        )
        if patient_name and not patient:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Paciente não encontrado")

        slot = None
        if doctor and data and hora:
            slot = (
                self.db.query(Horario)
                .filter(
                    Horario.medico_id == doctor.id,
                    Horario.data == data,
                    Horario.hora_inicio == hora,
                )
                .first()
            )

        status_text = "slot_disponivel" if slot and slot.disponivel else "slot_indisponivel"

        return {
            "intent": intent,
            "doctor": doctor.nome if doctor else doctor_name,
            "data": data,
            "hora": hora,
            "patient": patient.nome if patient else patient_name,
            "status": status_text,
            "slot_id": slot.id if slot else None,
        }

    def schedule_from_message(self, mensagem: str) -> dict[str, Any]:
        parsed = self.interpret(mensagem)
        doctor_name = parsed["doctor"]
        patient_name = parsed["patient"]
        data = parsed["data"]
        hora = parsed["hora"]

        if not doctor_name or not patient_name or not data or not hora:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Mensagem incompleta para agendamento")

        doctor = self.db.query(Medico).filter(Medico.nome.ilike(f"%{doctor_name}%")).first()
        if not doctor:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Médico não encontrado")

        patient = self.db.query(Paciente).filter(Paciente.nome.ilike(f"%{patient_name}%")).first()
        if not patient:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Paciente não encontrado")

        slot = (
            self.db.query(Horario)
            .filter(Horario.medico_id == doctor.id, Horario.data == data, Horario.hora_inicio == hora)
            .first()
        )
        if not slot:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Horário não encontrado")

        consulta_payload = ConsultaCreate(
            paciente_id=patient.id,
            medico_id=doctor.id,
            horario_id=slot.id,
            data=data,
            observacao="Agendamento realizado pelo assistente",
        )
        return ConsultaService(self.db).create(consulta_payload)

    def recommend_best_slot(self, mensagem: str) -> dict[str, Any]:
        text = self._normalize_text(mensagem)

        specialty = self._extract_specialty(text)
        if not specialty:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Especialidade não identificada")

        candidates = (
            self.db.query(Horario, Medico)
            .join(Medico, Horario.medico_id == Medico.id)
            .filter(Medico.especialidade.ilike(f"%{specialty}%"), Horario.disponivel.is_(True))
            .order_by(Horario.data.asc(), Horario.hora_inicio.asc())
            .all()
        )

        if not candidates:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Nenhum horário disponível encontrado")

        horario, medico = candidates[0]
        suggestion = (
            f"Sugestão: {medico.nome} - {medico.especialidade} - {horario.data} às {horario.hora_inicio}."
        )

        return {
            "especialidade": medico.especialidade,
            "medico": medico.nome,
            "data": horario.data,
            "hora": horario.hora_inicio,
            "mensagem": suggestion,
        }

    @staticmethod
    def _extract_specialty(text: str) -> str | None:
        for keyword in ["cardiologia", "neurologia", "pediatria", "dermatologia", "ortopedia", "ginecologia"]:
            if keyword in text:
                return keyword.capitalize()
        return None

    @staticmethod
    def _extract_doctor_name(text: str) -> str | None:
        segments = text.split(" com ")
        if len(segments) < 2:
            return None

        candidate = segments[1]
        for marker in [" para ", " as ", " às "]:
            if marker in candidate:
                candidate = candidate.split(marker, 1)[0]
        candidate = candidate.strip(" .")
        return candidate or None

    @staticmethod
    def _extract_date(text: str) -> str | None:
        match = re.search(r"(\d{4}-\d{2}-\d{2})", text)
        if match:
            return match.group(1)
        return None

    @staticmethod
    def _extract_time(text: str) -> str | None:
        match = re.search(r"(?:as|às)\s+(\d{2}:\d{2})", text)
        if match:
            return match.group(1)
        return None

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
