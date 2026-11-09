from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

from fastapi import APIRouter, Depends, FastAPI, status
from sqlalchemy.orm import Session

from app.backend.assistant.intent_service import AssistantIntentService
from app.backend.assistant.orchestrator import ChatOrchestrator, get_profile_classifier
from app.backend.core.clock import Clock, get_clock
from app.backend.core.database import get_db
from app.backend.core.dependencies import get_current_user_id
from app.backend.schemas.assistant import AssistantInterpretRequest, ChatRequest, ChatResponse
from app.backend.schemas.consulta import ConsultaOut


@asynccontextmanager
async def warm_up_models(_: FastAPI) -> AsyncIterator[None]:
    get_profile_classifier()
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


@router.post("/interpret")
def interpret_message(
    payload: AssistantInterpretRequest, db: Session = Depends(get_db), clock: Clock = Depends(get_clock)
) -> dict[str, Any]:
    return AssistantIntentService(db, clock).interpret(payload.mensagem)


@router.post("/agendar", response_model=ConsultaOut, status_code=status.HTTP_201_CREATED)
def agendar_consulta(
    payload: AssistantInterpretRequest, db: Session = Depends(get_db), clock: Clock = Depends(get_clock)
) -> ConsultaOut:
    return AssistantIntentService(db, clock).schedule_from_message(payload.mensagem)


@router.post("/recomendar")
def recomendar_consulta(
    payload: AssistantInterpretRequest, db: Session = Depends(get_db), clock: Clock = Depends(get_clock)
) -> dict[str, Any]:
    return AssistantIntentService(db, clock).recommend_best_slot(payload.mensagem)
