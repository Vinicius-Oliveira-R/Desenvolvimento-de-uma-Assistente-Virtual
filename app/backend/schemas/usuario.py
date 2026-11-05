from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator, model_validator

from app.backend.core.security import BCRYPT_LIMITE_BYTES
from app.backend.models.usuario import PapelUsuario, Usuario
from app.backend.schemas.medico import FichaMedico
from app.backend.schemas.paciente import FichaPaciente


class UsuarioCreate(BaseModel):
    nome: str = Field(..., min_length=2, max_length=150)
    email: EmailStr
    senha: str = Field(..., min_length=6, max_length=BCRYPT_LIMITE_BYTES)
    papel: PapelUsuario = PapelUsuario.PACIENTE
    paciente: FichaPaciente | None = None
    medico: FichaMedico | None = None

    @field_validator("senha")
    @classmethod
    def limitar_bytes_da_senha(cls, senha: str) -> str:
        if len(senha.encode()) > BCRYPT_LIMITE_BYTES:
            raise ValueError(f"A senha deve ter no máximo {BCRYPT_LIMITE_BYTES} bytes")
        return senha

    @model_validator(mode="after")
    def exigir_ficha_compativel_com_o_papel(self) -> "UsuarioCreate":
        if self.paciente and self.papel != PapelUsuario.PACIENTE:
            raise ValueError("A ficha de paciente só pode acompanhar um usuário com papel de paciente")
        if self.medico and self.papel != PapelUsuario.MEDICO:
            raise ValueError("A ficha de médico só pode acompanhar um usuário com papel de médico")
        return self


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


class PerfilOut(UsuarioOut):
    papeis_cadastraveis: list[PapelUsuario]

    @classmethod
    def from_usuario(cls, usuario: Usuario) -> "PerfilOut":
        return cls(
            id=usuario.id,
            nome=usuario.nome,
            email=usuario.email,
            papel=usuario.papel,
            papeis_cadastraveis=usuario.papel.papeis_cadastraveis(),
        )
