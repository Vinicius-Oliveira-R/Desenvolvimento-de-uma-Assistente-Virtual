from fastapi import HTTPException, status
from sqlalchemy.orm import Session

from app.backend.models import Medico
from app.backend.repositories.medico_repository import MedicoRepository
from app.backend.schemas.medico import MedicoCreate, MedicoOut


class MedicoService:
    def __init__(self, db: Session):
        self.repository = MedicoRepository(db)

    def create(self, payload: MedicoCreate) -> MedicoOut:
        medico = Medico(
            nome=payload.nome,
            crm=payload.crm,
            especialidade=payload.especialidade,
        )
        saved = self.repository.create(medico)
        return MedicoOut.model_validate(saved)

    def list_all(self) -> list[MedicoOut]:
        return [MedicoOut.model_validate(item) for item in self.repository.list_all()]

    def get_by_id(self, medico_id: int) -> MedicoOut:
        medico = self.repository.get_by_id(medico_id)
        if not medico:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Médico não encontrado")
        return MedicoOut.model_validate(medico)
