from pydantic import BaseModel, ConfigDict, Field


class FichaPaciente(BaseModel):
    cpf: str = Field(..., min_length=11, max_length=11)
    data_nascimento: str
    telefone: str = Field(..., min_length=10, max_length=20)


class PacienteCreate(FichaPaciente):
    usuario_id: int
    nome: str = Field(..., min_length=2, max_length=150)


class PacienteOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    usuario_id: int
    nome: str
    cpf: str
    data_nascimento: str
    telefone: str
