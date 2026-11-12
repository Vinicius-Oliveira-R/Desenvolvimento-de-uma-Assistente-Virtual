from datetime import date
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from app.backend.schemas.consulta import ConsultaDetalhadaOut


class AssistantInterpretRequest(BaseModel):
    mensagem: str = Field(..., min_length=3, max_length=500)


class TipoAcao(StrEnum):
    AGENDAR = "agendar"
    CANCELAR = "cancelar"
    RESPONDER_SOLICITACAO = "responder_solicitacao"


class CriteriosAgendamento(BaseModel):
    medico_nome: str | None = None
    especialidade: str | None = None
    data_inicio: date | None = None
    data_fim: date | None = None
    hora: str | None = None
    turno: str | None = None

    @property
    def possui_alvo(self) -> bool:
        return bool(self.medico_nome or self.especialidade)

    def merge(self, novos: "CriteriosAgendamento") -> "CriteriosAgendamento":
        novo_alvo = novos.possui_alvo
        nova_data = novos.data_inicio is not None
        novo_horario = bool(novos.hora or novos.turno)
        return CriteriosAgendamento(
            medico_nome=novos.medico_nome if novo_alvo else self.medico_nome,
            especialidade=novos.especialidade if novo_alvo else self.especialidade,
            data_inicio=novos.data_inicio if nova_data else self.data_inicio,
            data_fim=novos.data_fim if nova_data else self.data_fim,
            hora=novos.hora if novo_horario else self.hora,
            turno=novos.turno if novo_horario else self.turno,
        )

    def without_time(self) -> "CriteriosAgendamento":
        return self.model_copy(update={"hora": None})


class AcaoPendente(BaseModel):
    tipo: TipoAcao
    horario_id: int | None = None
    consulta_id: int | None = None
    notificacao_id: int | None = None
    criterios: CriteriosAgendamento = Field(default_factory=CriteriosAgendamento)
    recusados: list[int] = Field(default_factory=list)
    horarios_oferecidos: list[int] = Field(default_factory=list, max_length=6)
    aguardando_escolha: bool = False


class ContextoConversa(BaseModel):
    acao_pendente: AcaoPendente | None = None
    probabilidade_idoso: float | None = Field(default=None, ge=0, le=1)
    solicitacoes_vistas: list[int] = Field(default_factory=list)


class ChatRequest(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    mensagem: str = Field(..., min_length=1, max_length=500)
    contexto: ContextoConversa = Field(default_factory=ContextoConversa)


class HeuristicasOut(BaseModel):
    taxa_erros: float
    complexidade: float
    hesitacao: float
    vagueza: float
    informalidade: float


class ChatResponse(BaseModel):
    resposta: str
    perfil: str
    probabilidade_idoso: float
    intencao: str
    resultado: str
    entidades: dict[str, Any]
    heuristicas: HeuristicasOut
    contexto: ContextoConversa
    consulta: ConsultaDetalhadaOut | None = None
