from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

from fastapi import APIRouter, Depends, FastAPI, HTTPException, status
from sqlalchemy.orm import Session

from app.backend.assistant.intent_service import AssistantIntentService
from app.backend.assistant.orchestrator import ChatOrchestrator, get_profile_classifier
from app.backend.core.clock import Clock, get_clock
from app.backend.core.database import get_db
from app.backend.core.dependencies import get_current_user_id, get_current_user, require_admin_or_medico
from app.backend.schemas.assistant import AssistantInterpretRequest, ChatRequest, ChatResponse
from app.backend.schemas.consulta import ConsultaOut


@asynccontextmanager
async def warm_up_models(_: FastAPI) -> AsyncIterator[None]:
    # O classificador é carregado sob limite de tempo na primeira mensagem.
    # Falhas no ML não impedem o servidor ou a agenda determinística de funcionar.
    yield


router = APIRouter(prefix="/assistant", tags=["assistant"], lifespan=warm_up_models)


@router.post("/chat", response_model=ChatResponse)
def chat(
    payload: ChatRequest,
    usuario_id: int = Depends(get_current_user_id),
    db: Session = Depends(get_db),
    clock: Clock = Depends(get_clock),
) -> ChatResponse:
    return ChatOrchestrator.build(db, clock).reply(usuario_id, payload)


@router.post("/interpret", dependencies=[Depends(require_admin_or_medico)])
def interpret_message(
    payload: AssistantInterpretRequest, db: Session = Depends(get_db), clock: Clock = Depends(get_clock)
) -> dict[str, Any]:
    return AssistantIntentService(db, clock).interpret(payload.mensagem)


@router.post("/agendar", deprecated=True, dependencies=[Depends(get_current_user)])
def agendar_consulta(payload: AssistantInterpretRequest) -> None:
    # A mensagem jamais autoriza agir em nome de um paciente mencionado.
    raise HTTPException(status_code=410, detail="Use /api/assistant/chat e confirme a opção escolhida")


@router.post("/recomendar", dependencies=[Depends(get_current_user)])
def recomendar_consulta(
    payload: AssistantInterpretRequest, db: Session = Depends(get_db), clock: Clock = Depends(get_clock)
) -> dict[str, Any]:
    return AssistantIntentService(db, clock).recommend_best_slot(payload.mensagem)
