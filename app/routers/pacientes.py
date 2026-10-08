from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.security import decode_access_token
from app.schemas.paciente import PacienteCreate, PacienteOut
from app.services.paciente_service import PacienteService

router = APIRouter(prefix="/pacientes", tags=["pacientes"])
security = HTTPBearer()


@router.post("", response_model=PacienteOut, status_code=status.HTTP_201_CREATED)
def create_paciente(
    payload: PacienteCreate,
    credentials: HTTPAuthorizationCredentials = Depends(security),
    db: Session = Depends(get_db),
) -> PacienteOut:
    try:
        user_id = int(decode_access_token(credentials.credentials))
    except Exception as exc:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Token inválido") from exc
    return PacienteService(db).create(user_id, payload)


@router.get("", response_model=list[PacienteOut])
def list_pacientes(db: Session = Depends(get_db)) -> list[PacienteOut]:
    return PacienteService(db).list_all()
