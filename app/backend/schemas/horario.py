from datetime import date
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

DATA_ISO = r"^\d{4}-\d{2}-\d{2}$"
HORA_HHMM = r"^([01]\d|2[0-3]):[0-5]\d$"
MAXIMO_DE_DIAS_POR_LIBERACAO = 92


class HorarioCreate(BaseModel):
    medico_id: int
    data: str = Field(..., pattern=DATA_ISO)
    hora_inicio: str = Field(..., pattern=HORA_HHMM)
    hora_fim: str = Field(..., pattern=HORA_HHMM)

    @field_validator("data")
    @classmethod
    def data_real(cls, value: str) -> str:
        return date.fromisoformat(value).isoformat()

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


class LiberacaoDeHorarios(BaseModel):
    medico_id: int
    data_inicio: date
    data_fim: date
    dias_semana: list[Annotated[int, Field(ge=0, le=6)]] = Field(default=[0, 1, 2, 3, 4], min_length=1)
    hora_inicio: str = Field(..., pattern=HORA_HHMM)
    hora_fim: str = Field(..., pattern=HORA_HHMM)
    duracao_minutos: int = Field(default=30, ge=10, le=240)

    @field_validator("dias_semana")
    @classmethod
    def dias_sem_repeticao(cls, values: list[int]) -> list[int]:
        return sorted(set(values))

    @model_validator(mode="after")
    def validar_periodo(self) -> "LiberacaoDeHorarios":
        if self.data_fim < self.data_inicio:
            raise ValueError("data_fim deve ser igual ou posterior a data_inicio")
        if (self.data_fim - self.data_inicio).days >= MAXIMO_DE_DIAS_POR_LIBERACAO:
            raise ValueError(f"Libere no máximo {MAXIMO_DE_DIAS_POR_LIBERACAO} dias por vez")
        if self.hora_fim <= self.hora_inicio:
            raise ValueError("hora_fim deve ser posterior a hora_inicio")
        return self


class ResultadoDaLiberacao(BaseModel):
    criados: int
    ja_existentes: int
