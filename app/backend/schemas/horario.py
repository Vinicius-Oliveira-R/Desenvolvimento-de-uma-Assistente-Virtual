from pydantic import BaseModel, ConfigDict, Field, model_validator

DATA_ISO = r"^\d{4}-\d{2}-\d{2}$"
HORA_HHMM = r"^([01]\d|2[0-3]):[0-5]\d$"


class HorarioCreate(BaseModel):
    medico_id: int
    data: str = Field(..., pattern=DATA_ISO)
    hora_inicio: str = Field(..., pattern=HORA_HHMM)
    hora_fim: str = Field(..., pattern=HORA_HHMM)

    @model_validator(mode="after")
    def validar_intervalo(self) -> "HorarioCreate":
        if self.hora_fim <= self.hora_inicio:
            raise ValueError("hora_fim deve ser posterior a hora_inicio")
        return self


class HorarioOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    medico_id: int
    data: str
    hora_inicio: str
    hora_fim: str
    disponivel: bool
