from fastapi import APIRouter, Depends, status
from sqlalchemy.orm import Session

from app.backend.core.database import get_db
from app.backend.core.dependencies import get_current_user, require_admin_or_medico
from app.backend.models import Usuario
from app.backend.schemas.usuario import SessaoOut, UsuarioCreate, UsuarioLogin, UsuarioOut
from app.backend.services.auth_service import AuthService

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/register", response_model=UsuarioOut, status_code=status.HTTP_201_CREATED)
def register(
    payload: UsuarioCreate,
    solicitante: Usuario = Depends(require_admin_or_medico),
    db: Session = Depends(get_db),
) -> UsuarioOut:
    return AuthService(db).register(payload, solicitante)


@router.post("/login", response_model=SessaoOut)
def login(payload: UsuarioLogin, db: Session = Depends(get_db)) -> SessaoOut:
    return AuthService(db).login(payload)


@router.get("/me", response_model=UsuarioOut)
def get_me(usuario: Usuario = Depends(get_current_user)) -> UsuarioOut:
    return UsuarioOut.model_validate(usuario)
