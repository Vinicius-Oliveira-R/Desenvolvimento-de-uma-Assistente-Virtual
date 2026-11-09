from collections.abc import Callable

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from app.backend.core.database import get_db
from app.backend.core.exceptions import ForbiddenError
from app.backend.core.security import decode_access_token
from app.backend.models import PapelUsuario, Usuario
from app.backend.repositories.usuario_repository import UsuarioRepository

bearer_scheme = HTTPBearer(auto_error=False)


def get_current_user_id(credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme)) -> int:
    if credentials is None:
        raise _nao_autenticado("Autenticação necessária")
    try:
        return int(decode_access_token(credentials.credentials))
    except ValueError as exc:
        raise _nao_autenticado("Token inválido ou expirado") from exc


def get_current_user(usuario_id: int = Depends(get_current_user_id), db: Session = Depends(get_db)) -> Usuario:
    usuario = UsuarioRepository(db).get_by_id(usuario_id)
    if usuario is None:
        raise _nao_autenticado("Token inválido ou expirado")
    return usuario


def require_roles(*papeis: PapelUsuario) -> Callable[..., Usuario]:
    # O papel é lido do banco, não do token: rebaixar um usuário vale já na requisição seguinte.
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


def _nao_autenticado(detalhe: str) -> HTTPException:
    return HTTPException(status.HTTP_401_UNAUTHORIZED, detail=detalhe, headers={"WWW-Authenticate": "Bearer"})
