from sqlalchemy import func
from sqlalchemy.orm import Session

from app.backend.models import Usuario


class UsuarioRepository:
    def __init__(self, db: Session):
        self.db = db

    def get_by_id(self, usuario_id: int) -> Usuario | None:
        return self.db.get(Usuario, usuario_id)

    def get_by_email(self, email: str) -> Usuario | None:
        return self.db.query(Usuario).filter(func.lower(Usuario.email) == email.strip().lower()).first()

    def add(self, usuario: Usuario) -> Usuario:
        self.db.add(usuario)
        self.db.flush()
        return usuario
