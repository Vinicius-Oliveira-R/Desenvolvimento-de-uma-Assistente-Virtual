from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field, model_validator


class TipoSolicitacao(StrEnum):
    REAGENDAMENTO = "reagendamento"
    CANCELAMENTO = "cancelamento"


class SolicitacaoAlteracao(BaseModel):
    tipo: TipoSolicitacao
    horario_id: int | None = None
    motivo: str | None = Field(default=None, max_length=200)

    @model_validator(mode="after")
    def exigir_horario_na_remarcacao(self) -> "SolicitacaoAlteracao":
        if self.tipo == TipoSolicitacao.REAGENDAMENTO and self.horario_id is None:
            raise ValueError("Informe o novo horário da remarcação")
        return self


class RespostaNotificacao(BaseModel):
    aceitar: bool


class NotificacaoOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    consulta_id: int
    tipo: str
    status: str
    mensagem: str
    criado_em: str
    acao_necessaria: bool = Field(validation_alias="e_solicitacao")
