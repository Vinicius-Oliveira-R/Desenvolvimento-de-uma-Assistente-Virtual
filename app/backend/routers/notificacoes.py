from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.backend.core.database import get_db
from app.backend.core.dependencies import get_current_user
from app.backend.models import Usuario
from app.backend.schemas.notificacao import NotificacaoOut, RespostaNotificacao
from app.backend.services.notificacao_service import NotificacaoService

router = APIRouter(prefix="/notificacoes", tags=["notificacoes"])


@router.get("", response_model=list[NotificacaoOut])
def list_notificacoes(
    usuario: Usuario = Depends(get_current_user), db: Session = Depends(get_db)
) -> list[NotificacaoOut]:
    return NotificacaoService(db).listar_pendentes(usuario)


@router.post("/{notificacao_id}/responder", response_model=NotificacaoOut)
def responder_notificacao(
    notificacao_id: int,
    resposta: RespostaNotificacao,
    usuario: Usuario = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> NotificacaoOut:
    return NotificacaoService(db).responder(notificacao_id, usuario, resposta.aceitar)
