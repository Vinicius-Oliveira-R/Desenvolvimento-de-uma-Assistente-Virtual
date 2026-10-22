from pydantic import BaseModel, ConfigDict, EmailStr, Field


class UsuarioCreate(BaseModel):
    nome: str = Field(..., min_length=2, max_length=150)
    email: EmailStr
    senha: str = Field(..., min_length=6, max_length=255)
    tipo: str = Field(default="paciente", max_length=50)


class UsuarioLogin(BaseModel):
    email: EmailStr
    senha: str = Field(..., min_length=6)


class UsuarioOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    nome: str
    email: str
    tipo: str
    token: str | None = None
