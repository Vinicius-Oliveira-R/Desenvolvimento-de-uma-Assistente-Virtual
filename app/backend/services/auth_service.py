from sqlalchemy.orm import Session

from app.backend.core.exceptions import BusinessRuleError, UnauthorizedError
from app.backend.core.security import create_access_token, get_password_hash, verify_password
from app.backend.models import Usuario
from app.backend.repositories.usuario_repository import UsuarioRepository
from app.backend.schemas.usuario import UsuarioCreate, UsuarioLogin, UsuarioOut


class AuthService:
    def __init__(self, db: Session):
        self.repository = UsuarioRepository(db)

    def register(self, payload: UsuarioCreate) -> UsuarioOut:
        existing = self.repository.get_by_email(payload.email)
        if existing:
            raise BusinessRuleError("Email já cadastrado")

        usuario = Usuario(
            nome=payload.nome,
            email=payload.email,
            senha_hash=get_password_hash(payload.senha),
            tipo=payload.tipo,
        )
        saved = self.repository.create(usuario)
        token = create_access_token(str(saved.id))
        return UsuarioOut(id=saved.id, nome=saved.nome, email=saved.email, tipo=saved.tipo, token=token)

    def login(self, payload: UsuarioLogin) -> UsuarioOut:
        usuario = self.repository.get_by_email(payload.email)
        if not usuario or not verify_password(payload.senha, usuario.senha_hash):
            raise UnauthorizedError("Credenciais inválidas")

        token = create_access_token(str(usuario.id))
        return UsuarioOut(id=usuario.id, nome=usuario.nome, email=usuario.email, tipo=usuario.tipo, token=token)
