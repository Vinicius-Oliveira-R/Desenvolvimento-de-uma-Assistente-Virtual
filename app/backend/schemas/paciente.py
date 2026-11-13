from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.backend.core.validation import normalize_birth_date, normalize_cpf, normalize_phone


class FichaPaciente(BaseModel):
    cpf: str
    data_nascimento: str
    telefone: str

    _cpf = field_validator("cpf")(normalize_cpf)
    _data = field_validator("data_nascimento")(normalize_birth_date)
    _telefone = field_validator("telefone")(normalize_phone)


class PacienteCreate(FichaPaciente):
    usuario_id: int = Field(gt=0)
    nome: str = Field(..., min_length=2, max_length=150)


class PacienteOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    usuario_id: int
    nome: str
    cpf: str
    data_nascimento: str
    telefone: str
