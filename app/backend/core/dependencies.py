from collections.abc import Callable

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from app.backend.core.database import get_db
from app.backend.core.exceptions import ForbiddenError
from app.backend.core.security import decode_token_claims
from app.backend.models import PapelUsuario, Usuario
from app.backend.repositories.usuario_repository import UsuarioRepository

bearer_scheme = HTTPBearer(auto_error=False)


def _nao_autenticado(detalhe: str) -> HTTPException:
    return HTTPException(status.HTTP_401_UNAUTHORIZED, detail=detalhe, headers={"WWW-Authenticate": "Bearer"})


def get_current_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme), db: Session = Depends(get_db)
) -> Usuario:
    if credentials is None:
        raise _nao_autenticado("Autenticação necessária")
    try:
        claims = decode_token_claims(credentials.credentials)
        usuario = UsuarioRepository(db).get_by_id(int(claims["sub"]))
    except (ValueError, KeyError, TypeError) as exc:
        raise _nao_autenticado("Token inválido ou expirado") from exc
    if usuario is None or not usuario.ativo or claims["ver"] != usuario.token_version:
        raise _nao_autenticado("Token inválido ou expirado")
    return usuario


def get_current_user_id(usuario: Usuario = Depends(get_current_user)) -> int:
    return usuario.id


def require_roles(*papeis: PapelUsuario) -> Callable[..., Usuario]:
    def verificar_papel(usuario: Usuario = Depends(get_current_user)) -> Usuario:
        if usuario.papel not in papeis:
            raise ForbiddenError("Seu perfil não tem permissão para esta operação")
        return usuario
    return verificar_papel


def require_can_register(papel: PapelUsuario) -> Callable[..., Usuario]:
    def verificar_cadastro(usuario: Usuario = Depends(get_current_user)) -> Usuario:
        if not usuario.papel.pode_cadastrar(papel):
            raise ForbiddenError("Seu perfil não tem permissão para esta operação")
        return usuario
    return verificar_cadastro


require_admin_or_medico = require_roles(PapelUsuario.ADMIN, PapelUsuario.MEDICO)
require_gestor = require_roles(PapelUsuario.GESTOR)
