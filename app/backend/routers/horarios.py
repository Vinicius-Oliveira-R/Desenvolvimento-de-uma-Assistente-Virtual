from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.orm import Session

from app.backend.core.database import get_db
from app.backend.schemas.horario import DATA_ISO, HorarioCreate, HorarioOut
from app.backend.services.horario_service import HorarioService

router = APIRouter(prefix="/horarios", tags=["horarios"])


@router.post("", response_model=HorarioOut, status_code=status.HTTP_201_CREATED)
def create_horario(payload: HorarioCreate, db: Session = Depends(get_db)) -> HorarioOut:
    return HorarioService(db).create(payload)


@router.get("", response_model=list[HorarioOut])
def list_horarios(
    medico_id: int | None = None,
    data: str | None = Query(None, pattern=DATA_ISO),
    disponivel: bool | None = None,
    db: Session = Depends(get_db),
) -> list[HorarioOut]:
    return HorarioService(db).list(medico_id=medico_id, data=data, disponivel=disponivel)
