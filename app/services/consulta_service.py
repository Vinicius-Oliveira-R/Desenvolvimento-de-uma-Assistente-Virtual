from datetime import datetime, timezone

from fastapi import HTTPException, status
from sqlalchemy.orm import Session

from app.models import Consulta, Horario, Medico, Paciente
from app.repositories.consulta_repository import ConsultaRepository
from app.schemas.consulta import ConfirmacaoConsulta, ConsultaCreate, ConsultaOut, ConsultaUpdate


class ConsultaService:
    def __init__(self, db: Session):
        self.repository = ConsultaRepository(db)
        self.db = db

    @staticmethod
    def _utc_now() -> str:
        return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    def create(self, payload: ConsultaCreate) -> ConsultaOut:
        paciente = self.db.query(Paciente).filter(Paciente.id == payload.paciente_id).first()
        medico = self.db.query(Medico).filter(Medico.id == payload.medico_id).first()
        horario = self.db.query(Horario).filter(Horario.id == payload.horario_id).first()

        if not paciente:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Paciente não encontrado")
        if not medico:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Médico não encontrado")
        if not horario:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Horário não encontrado")

        if not horario.disponivel:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Horário indisponível")

        existing = (
            self.db.query(Consulta)
            .filter(Consulta.horario_id == payload.horario_id, Consulta.status != "cancelada")
            .first()
        )
        if existing:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Horário já reservado")

        consulta = Consulta(
            paciente_id=payload.paciente_id,
            medico_id=payload.medico_id,
            horario_id=payload.horario_id,
            data=payload.data,
            status="agendada",
            observacao=payload.observacao,
            data_criacao=self._utc_now(),
            data_atualizacao=self._utc_now(),
        )
        saved = self.repository.create(consulta)
        horario.disponivel = False
        self.db.commit()
        return ConsultaOut.model_validate(saved)

    def list_all(self) -> list[ConsultaOut]:
        return [ConsultaOut.model_validate(item) for item in self.repository.list_all()]

    def get_by_id(self, consulta_id: int) -> ConsultaOut:
        consulta = self.repository.get_by_id(consulta_id)
        if not consulta:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Consulta não encontrada")
        return ConsultaOut.model_validate(consulta)

    def update(self, consulta_id: int, payload: ConsultaUpdate) -> ConsultaOut:
        consulta = self.repository.get_by_id(consulta_id)
        if not consulta:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Consulta não encontrada")

        has_changes = (
            payload.medico_id is not None
            or payload.horario_id is not None
            or payload.data is not None
            or payload.status is not None
            or payload.observacao is not None
        )
        if has_changes and not payload.confirmado:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="A alteração da consulta exige confirmação explícita do paciente.",
            )

        if payload.medico_id is not None:
            consulta.medico_id = payload.medico_id
        if payload.horario_id is not None:
            consulta.horario_id = payload.horario_id
        if payload.data is not None:
            consulta.data = payload.data
        if payload.status is not None:
            consulta.status = payload.status
        if payload.observacao is not None:
            consulta.observacao = payload.observacao

        consulta.data_atualizacao = self._utc_now()
        return ConsultaOut.model_validate(self.repository.update(consulta))

    def cancel(self, consulta_id: int, payload: ConfirmacaoConsulta) -> ConsultaOut:
        consulta = self.repository.get_by_id(consulta_id)
        if not consulta:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Consulta não encontrada")
        if consulta.status == "cancelada":
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Consulta já cancelada")
        if not payload.confirmado:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="O cancelamento da consulta exige confirmação explícita.",
            )

        consulta.status = "cancelada"
        consulta.data_atualizacao = self._utc_now()
        horario = self.db.query(Horario).filter(Horario.id == consulta.horario_id).first()
        if horario:
            horario.disponivel = True
        return ConsultaOut.model_validate(self.repository.update(consulta))
