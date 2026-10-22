from fastapi import APIRouter, Depends, status
from sqlalchemy.orm import Session

from app.backend.core.database import get_db
from app.backend.schemas.horario import HorarioCreate, HorarioOut
from app.backend.services.horario_service import HorarioService

router = APIRouter(prefix="/horarios", tags=["horarios"])


@router.post("", response_model=HorarioOut, status_code=status.HTTP_201_CREATED)
def create_horario(payload: HorarioCreate, db: Session = Depends(get_db)) -> HorarioOut:
    return HorarioService(db).create(payload)


@router.get("", response_model=list[HorarioOut])
def list_horarios(db: Session = Depends(get_db)) -> list[HorarioOut]:
    return HorarioService(db).list_all()
