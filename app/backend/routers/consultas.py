from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.orm import Session

from app.backend.core.database import get_db
from app.backend.core.dependencies import get_current_user_id, require_admin_or_medico
from app.backend.models import StatusConsulta, Usuario
from app.backend.repositories.consulta_repository import FiltroAgenda
from app.backend.schemas.consulta import (
    ConfirmacaoConsulta,
    ConsultaAgendaOut,
    ConsultaCreate,
    ConsultaDetalhadaOut,
    ConsultaOut,
    ConsultaUpdate,
)
from app.backend.schemas.horario import DATA_ISO
from app.backend.schemas.notificacao import NotificacaoOut, SolicitacaoAlteracao
from app.backend.services.consulta_service import ConsultaService
from app.backend.services.notificacao_service import NotificacaoService

router = APIRouter(prefix="/consultas", tags=["consultas"])
SOMENTE_EQUIPE_CLINICA = [Depends(require_admin_or_medico)]


@router.post(
    "", response_model=ConsultaOut, status_code=status.HTTP_201_CREATED, dependencies=SOMENTE_EQUIPE_CLINICA
)
def create_consulta(payload: ConsultaCreate, db: Session = Depends(get_db)) -> ConsultaOut:
    return ConsultaService(db).create(payload)


@router.get("", response_model=list[ConsultaAgendaOut], dependencies=SOMENTE_EQUIPE_CLINICA)
def list_consultas(
    data_inicio: str | None = Query(None, pattern=DATA_ISO),
    data_fim: str | None = Query(None, pattern=DATA_ISO),
    medico_id: int | None = None,
    situacao: StatusConsulta | None = Query(None, alias="status"),
    db: Session = Depends(get_db),
) -> list[ConsultaAgendaOut]:
    filtro = FiltroAgenda(data_inicio=data_inicio, data_fim=data_fim, medico_id=medico_id, status=situacao)
    return ConsultaService(db).list_agenda(filtro)


@router.get("/minhas", response_model=list[ConsultaDetalhadaOut])
def list_minhas_consultas(
    usuario_id: int = Depends(get_current_user_id), db: Session = Depends(get_db)
) -> list[ConsultaDetalhadaOut]:
    return ConsultaService(db).list_by_usuario(usuario_id)


@router.get("/{consulta_id}", response_model=ConsultaAgendaOut, dependencies=SOMENTE_EQUIPE_CLINICA)
def get_consulta(consulta_id: int, db: Session = Depends(get_db)) -> ConsultaAgendaOut:
    return ConsultaService(db).get_da_agenda(consulta_id)


@router.post(
    "/{consulta_id}/solicitacoes", response_model=NotificacaoOut, status_code=status.HTTP_201_CREATED
)
def solicitar_alteracao(
    consulta_id: int,
    pedido: SolicitacaoAlteracao,
    solicitante: Usuario = Depends(require_admin_or_medico),
    db: Session = Depends(get_db),
) -> NotificacaoOut:
    return NotificacaoService(db).solicitar(consulta_id, pedido, solicitante)


@router.put("/{consulta_id}", response_model=ConsultaOut)
def update_consulta(
    consulta_id: int,
    payload: ConsultaUpdate,
    solicitante: Usuario = Depends(require_admin_or_medico),
    db: Session = Depends(get_db),
) -> ConsultaOut:
    consulta = ConsultaService(db).update(consulta_id, payload)
    if payload.horario_id is not None or payload.status == StatusConsulta.CANCELADA:
        cancelada = payload.status == StatusConsulta.CANCELADA
        NotificacaoService(db).avisar_paciente_sobre_alteracao(consulta_id, solicitante, cancelada)
    return consulta


@router.delete("/{consulta_id}", response_model=ConsultaOut)
def cancel_consulta(
    consulta_id: int,
    payload: ConfirmacaoConsulta,
    solicitante: Usuario = Depends(require_admin_or_medico),
    db: Session = Depends(get_db),
) -> ConsultaOut:
    consulta = ConsultaService(db).cancel(consulta_id, payload)
    NotificacaoService(db).avisar_paciente_sobre_alteracao(consulta_id, solicitante, cancelada=True)
    return consulta
