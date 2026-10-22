from typing import Any

from fastapi import APIRouter, Depends, status
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.backend.assistant.intent_service import AssistantIntentService
from app.backend.core.database import get_db
from app.backend.schemas.consulta import ConsultaOut

router = APIRouter(prefix="/assistant", tags=["assistant"])


class AssistantInterpretRequest(BaseModel):
    mensagem: str = Field(..., min_length=3, max_length=500)


@router.post("/interpret")
def interpret_message(payload: AssistantInterpretRequest, db: Session = Depends(get_db)) -> dict[str, Any]:
    return AssistantIntentService(db).interpret(payload.mensagem)


@router.post("/agendar", response_model=ConsultaOut, status_code=status.HTTP_201_CREATED)
def agendar_consulta(payload: AssistantInterpretRequest, db: Session = Depends(get_db)) -> ConsultaOut:
    return AssistantIntentService(db).schedule_from_message(payload.mensagem)


@router.post("/recomendar")
def recomendar_consulta(payload: AssistantInterpretRequest, db: Session = Depends(get_db)) -> dict[str, Any]:
    return AssistantIntentService(db).recommend_best_slot(payload.mensagem)
