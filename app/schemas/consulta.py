from pydantic import BaseModel, ConfigDict, Field


class ConsultaCreate(BaseModel):
    paciente_id: int
    medico_id: int
    horario_id: int
    data: str = Field(..., min_length=8, max_length=30)
    observacao: str | None = None


class ConsultaUpdate(BaseModel):
    medico_id: int | None = None
    horario_id: int | None = None
    data: str | None = None
    status: str | None = None
    observacao: str | None = None
    confirmado: bool = False


class ConfirmacaoConsulta(BaseModel):
    confirmado: bool = False


class ConsultaOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    paciente_id: int
    medico_id: int
    horario_id: int
    data: str
    status: str
    observacao: str | None = None
    data_criacao: str
    data_atualizacao: str
