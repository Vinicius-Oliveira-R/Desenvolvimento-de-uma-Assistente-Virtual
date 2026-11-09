from fastapi import APIRouter, Depends, status
from sqlalchemy.orm import Session

from app.backend.core.database import get_db
from app.backend.core.dependencies import require_admin_or_medico, require_can_register
from app.backend.models import PapelUsuario
from app.backend.schemas.paciente import PacienteCreate, PacienteOut
from app.backend.services.paciente_service import PacienteService

router = APIRouter(prefix="/pacientes", tags=["pacientes"])


@router.post(
    "",
    response_model=PacienteOut,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(require_can_register(PapelUsuario.PACIENTE))],
)
def create_paciente(payload: PacienteCreate, db: Session = Depends(get_db)) -> PacienteOut:
    return PacienteService(db).create(payload)


@router.get("", response_model=list[PacienteOut], dependencies=[Depends(require_admin_or_medico)])
def list_pacientes(db: Session = Depends(get_db)) -> list[PacienteOut]:
    return PacienteService(db).list_all()
