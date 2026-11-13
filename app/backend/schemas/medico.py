from pydantic import BaseModel, ConfigDict, Field


class FichaMedico(BaseModel):
    crm: str = Field(..., min_length=3, max_length=30)
    especialidade: str = Field(..., min_length=2, max_length=100)


class MedicoCreate(FichaMedico):
    nome: str = Field(..., min_length=2, max_length=150)


class MedicoOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    nome: str
    crm: str
    especialidade: str
    ativo: bool = True
