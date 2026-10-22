from fastapi import HTTPException, status
from sqlalchemy.orm import Session

from app.backend.models import Paciente, Usuario
from app.backend.repositories.paciente_repository import PacienteRepository
from app.backend.schemas.paciente import PacienteCreate, PacienteOut


class PacienteService:
    def __init__(self, db: Session):
        self.repository = PacienteRepository(db)
        self.db = db

    def create(self, usuario_id: int, payload: PacienteCreate) -> PacienteOut:
        usuario = self.db.query(Usuario).filter(Usuario.id == usuario_id).first()
        if not usuario:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Usuário não encontrado")

        paciente = Paciente(
            usuario_id=usuario_id,
            nome=payload.nome,
            cpf=payload.cpf,
            data_nascimento=payload.data_nascimento,
            telefone=payload.telefone,
        )
        saved = self.repository.create(paciente)
        return PacienteOut.model_validate(saved)

    def list_all(self) -> list[PacienteOut]:
        return [PacienteOut.model_validate(item) for item in self.repository.list_all()]
