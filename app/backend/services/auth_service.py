from sqlalchemy.orm import Session

from app.backend.core.exceptions import BusinessRuleError, ForbiddenError, UnauthorizedError
from app.backend.core.security import create_access_token, get_password_hash, verify_password
from app.backend.models import Usuario
from app.backend.repositories.usuario_repository import UsuarioRepository
from app.backend.schemas.usuario import SessaoOut, UsuarioCreate, UsuarioLogin, UsuarioOut


class AuthService:
    def __init__(self, db: Session):
        self.repository = UsuarioRepository(db)

    def register(self, payload: UsuarioCreate, solicitante: Usuario) -> UsuarioOut:
        if not solicitante.papel.pode_cadastrar(payload.papel):
            raise ForbiddenError(f"Seu perfil não pode cadastrar usuários com o papel '{payload.papel}'")
        if self.repository.get_by_email(payload.email):
            raise BusinessRuleError("Email já cadastrado")

        usuario = Usuario(
            nome=payload.nome,
            email=payload.email,
            senha_hash=get_password_hash(payload.senha),
            papel=payload.papel,
        )
        return UsuarioOut.model_validate(self.repository.create(usuario))

    def login(self, payload: UsuarioLogin) -> SessaoOut:
        usuario = self.repository.get_by_email(payload.email)
        if not usuario or not verify_password(payload.senha, usuario.senha_hash):
            raise UnauthorizedError("Credenciais inválidas")

        token = create_access_token(str(usuario.id))
        return SessaoOut(id=usuario.id, nome=usuario.nome, email=usuario.email, papel=usuario.papel, token=token)
