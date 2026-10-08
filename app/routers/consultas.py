from fastapi import APIRouter, Depends, status
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.schemas.consulta import ConfirmacaoConsulta, ConsultaCreate, ConsultaOut, ConsultaUpdate
from app.services.consulta_service import ConsultaService

router = APIRouter(prefix="/consultas", tags=["consultas"])


@router.post("", response_model=ConsultaOut, status_code=status.HTTP_201_CREATED)
def create_consulta(payload: ConsultaCreate, db: Session = Depends(get_db)) -> ConsultaOut:
    return ConsultaService(db).create(payload)


@router.get("", response_model=list[ConsultaOut])
def list_consultas(db: Session = Depends(get_db)) -> list[ConsultaOut]:
    return ConsultaService(db).list_all()


@router.get("/{consulta_id}", response_model=ConsultaOut)
def get_consulta(consulta_id: int, db: Session = Depends(get_db)) -> ConsultaOut:
    return ConsultaService(db).get_by_id(consulta_id)


@router.put("/{consulta_id}", response_model=ConsultaOut)
def update_consulta(consulta_id: int, payload: ConsultaUpdate, db: Session = Depends(get_db)) -> ConsultaOut:
    return ConsultaService(db).update(consulta_id, payload)


@router.delete("/{consulta_id}", response_model=ConsultaOut)
def cancel_consulta(consulta_id: int, payload: ConfirmacaoConsulta, db: Session = Depends(get_db)) -> ConsultaOut:
    return ConsultaService(db).cancel(consulta_id, payload)
