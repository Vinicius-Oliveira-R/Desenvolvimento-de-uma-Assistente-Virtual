from fastapi import APIRouter, Depends, status
from sqlalchemy.orm import Session

from app.backend.core.database import get_db
from app.backend.core.dependencies import get_current_user_id
from app.backend.schemas.paciente import PacienteCreate, PacienteOut
from app.backend.services.paciente_service import PacienteService

router = APIRouter(prefix="/pacientes", tags=["pacientes"])


@router.post("", response_model=PacienteOut, status_code=status.HTTP_201_CREATED)
def create_paciente(
    payload: PacienteCreate,
    usuario_id: int = Depends(get_current_user_id),
    db: Session = Depends(get_db),
) -> PacienteOut:
    return PacienteService(db).create(usuario_id, payload)


@router.get("", response_model=list[PacienteOut])
def list_pacientes(db: Session = Depends(get_db)) -> list[PacienteOut]:
    return PacienteService(db).list_all()
