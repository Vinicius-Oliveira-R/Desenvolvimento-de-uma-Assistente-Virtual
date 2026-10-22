from pydantic import BaseModel, ConfigDict, Field


class HorarioCreate(BaseModel):
    medico_id: int
    data: str = Field(..., min_length=8, max_length=30)
    hora_inicio: str = Field(..., min_length=5, max_length=5)
    hora_fim: str = Field(..., min_length=5, max_length=5)


class HorarioOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    medico_id: int
    data: str
    hora_inicio: str
    hora_fim: str
    disponivel: bool
