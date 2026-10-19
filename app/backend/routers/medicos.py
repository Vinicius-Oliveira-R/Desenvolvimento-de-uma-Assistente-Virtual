from fastapi import APIRouter, Depends, status
from sqlalchemy.orm import Session

from app.backend.core.database import get_db
from app.backend.schemas.medico import MedicoCreate, MedicoOut
from app.backend.services.medico_service import MedicoService

router = APIRouter(prefix="/medicos", tags=["medicos"])


@router.post("", response_model=MedicoOut, status_code=status.HTTP_201_CREATED)
def create_medico(payload: MedicoCreate, db: Session = Depends(get_db)) -> MedicoOut:
    return MedicoService(db).create(payload)


@router.get("", response_model=list[MedicoOut])
def list_medicos(db: Session = Depends(get_db)) -> list[MedicoOut]:
    return MedicoService(db).list_all()


@router.get("/{medico_id}", response_model=MedicoOut)
def get_medico(medico_id: int, db: Session = Depends(get_db)) -> MedicoOut:
    return MedicoService(db).get_by_id(medico_id)
