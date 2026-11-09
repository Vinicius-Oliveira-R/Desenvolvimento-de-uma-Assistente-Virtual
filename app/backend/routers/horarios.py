from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.orm import Session

from app.backend.core.clock import Clock, get_clock
from app.backend.core.database import get_db
from app.backend.core.dependencies import require_admin_or_medico
from app.backend.schemas.horario import (
    DATA_ISO,
    HorarioCreate,
    HorarioOut,
    LiberacaoDeHorarios,
    ResultadoDaLiberacao,
)
from app.backend.services.horario_service import HorarioService

router = APIRouter(prefix="/horarios", tags=["horarios"])


SOMENTE_EQUIPE_CLINICA = [Depends(require_admin_or_medico)]


@router.post(
    "", response_model=HorarioOut, status_code=status.HTTP_201_CREATED, dependencies=SOMENTE_EQUIPE_CLINICA
)
def create_horario(payload: HorarioCreate, db: Session = Depends(get_db)) -> HorarioOut:
    return HorarioService(db).create(payload)


@router.post(
    "/lote",
    response_model=ResultadoDaLiberacao,
    status_code=status.HTTP_201_CREATED,
    dependencies=SOMENTE_EQUIPE_CLINICA,
)
def liberar_horarios(
    pedido: LiberacaoDeHorarios, db: Session = Depends(get_db), clock: Clock = Depends(get_clock)
) -> ResultadoDaLiberacao:
    return HorarioService(db).liberar(pedido, clock.today())


@router.get("", response_model=list[HorarioOut])
def list_horarios(
    medico_id: int | None = None,
    data: str | None = Query(None, pattern=DATA_ISO),
    disponivel: bool | None = None,
    db: Session = Depends(get_db),
) -> list[HorarioOut]:
    return HorarioService(db).list(medico_id=medico_id, data=data, disponivel=disponivel)
