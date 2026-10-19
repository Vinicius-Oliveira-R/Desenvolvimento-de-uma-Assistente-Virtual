from fastapi import HTTPException, status
from sqlalchemy.orm import Session

from app.backend.models import Horario, Medico
from app.backend.repositories.horario_repository import HorarioRepository
from app.backend.schemas.horario import HorarioCreate, HorarioOut


class HorarioService:
    def __init__(self, db: Session):
        self.repository = HorarioRepository(db)
        self.db = db

    def create(self, payload: HorarioCreate) -> HorarioOut:
        medico = self.db.query(Medico).filter(Medico.id == payload.medico_id).first()
        if not medico:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Médico não encontrado")

        horario = Horario(
            medico_id=payload.medico_id,
            data=payload.data,
            hora_inicio=payload.hora_inicio,
            hora_fim=payload.hora_fim,
            disponivel=True,
        )
        saved = self.repository.create(horario)
        return HorarioOut.model_validate(saved)

    def list_all(self) -> list[HorarioOut]:
        return [HorarioOut.model_validate(item) for item in self.repository.list_all()]
