from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from app.backend.core.database import get_db
from app.backend.core.security import decode_access_token
from app.backend.schemas.usuario import UsuarioCreate, UsuarioLogin, UsuarioOut
from app.backend.services.auth_service import AuthService

router = APIRouter(prefix="/auth", tags=["auth"])
security = HTTPBearer()


@router.post("/register", response_model=UsuarioOut, status_code=status.HTTP_201_CREATED)
def register(payload: UsuarioCreate, db: Session = Depends(get_db)) -> UsuarioOut:
    return AuthService(db).register(payload)


@router.post("/login", response_model=UsuarioOut)
def login(payload: UsuarioLogin, db: Session = Depends(get_db)) -> UsuarioOut:
    return AuthService(db).login(payload)


@router.get("/me")
def get_me(
    credentials: HTTPAuthorizationCredentials = Depends(security),
    db: Session = Depends(get_db),
):
    token = credentials.credentials
    try:
        user_id = decode_access_token(token)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=str(exc)) from exc

    return {"user_id": user_id, "token": token}
