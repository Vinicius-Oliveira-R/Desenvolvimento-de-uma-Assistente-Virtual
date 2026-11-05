from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator

from app.backend.core.security import BCRYPT_LIMITE_BYTES
from app.backend.models.usuario import PapelUsuario


class UsuarioCreate(BaseModel):
    nome: str = Field(..., min_length=2, max_length=150)
    email: EmailStr
    senha: str = Field(..., min_length=6, max_length=BCRYPT_LIMITE_BYTES)
    papel: PapelUsuario = PapelUsuario.PACIENTE

    @field_validator("senha")
    @classmethod
    def limitar_bytes_da_senha(cls, senha: str) -> str:
        if len(senha.encode()) > BCRYPT_LIMITE_BYTES:
            raise ValueError(f"A senha deve ter no máximo {BCRYPT_LIMITE_BYTES} bytes")
        return senha


class UsuarioLogin(BaseModel):
    email: EmailStr
    senha: str = Field(..., min_length=6)


class UsuarioOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    nome: str
    email: str
    papel: PapelUsuario


class SessaoOut(UsuarioOut):
    token: str
