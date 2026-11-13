from fastapi import APIRouter, Depends, Request, status
from sqlalchemy.orm import Session

from app.backend.core.database import get_db
from app.backend.core.dependencies import get_current_user
from app.backend.models import Usuario
from app.backend.schemas.usuario import PerfilOut, SessaoOut, UsuarioCreate, UsuarioLogin, UsuarioOut
from app.backend.services.auth_service import AuthService
from app.backend.services.login_throttle import LoginThrottle

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/register", response_model=UsuarioOut, status_code=status.HTTP_201_CREATED)
def register(
    payload: UsuarioCreate,
    solicitante: Usuario = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> UsuarioOut:
    return AuthService(db).register(payload, solicitante)


@router.post("/login", response_model=SessaoOut)
def login(payload: UsuarioLogin, request: Request, db: Session = Depends(get_db)) -> SessaoOut:
    throttle = LoginThrottle(db)
    # Não confia diretamente em X-Forwarded-For; configure somente proxies conhecidos no servidor.
    throttle.consume(str(payload.email), request.client.host if request.client else "unknown")
    sessao = AuthService(db).login(payload)
    throttle.success(str(payload.email))
    return sessao


@router.get("/me", response_model=PerfilOut)
def get_me(usuario: Usuario = Depends(get_current_user)) -> PerfilOut:
    return PerfilOut.from_usuario(usuario)
