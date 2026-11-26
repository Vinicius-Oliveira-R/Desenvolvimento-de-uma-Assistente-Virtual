from datetime import date
from enum import StrEnum
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, computed_field

from app.backend.assistant.communication_style import EstiloComunicacao
from app.backend.schemas.consulta import ConsultaDetalhadaOut

TOKEN_DE_PROPOSTA = r"^[A-Za-z0-9_-]{4,32}$"


class AssistantInterpretRequest(BaseModel):
    mensagem: str = Field(..., min_length=3, max_length=500)


class TipoAcao(StrEnum):
    AGENDAR = "agendar"
    REMARCAR = "remarcar"
    CANCELAR = "cancelar"
    GERENCIAR = "gerenciar"
    RESPONDER_SOLICITACAO = "responder_solicitacao"


class Pergunta(StrEnum):
    """Última pergunta apresentada ao paciente; só as de confirmação podem alterar a agenda."""

    NOVA_BUSCA = "nova_busca"
    ESCOLHER_HORARIO = "escolher_horario"
    CONFIRMAR_HORARIO = "confirmar_horario"
    ESCOLHER_CONSULTA = "escolher_consulta"
    ESCOLHER_ACAO = "escolher_acao"
    INFORMAR_DESTINO = "informar_destino"
    CONFIRMAR_TROCA = "confirmar_troca"
    CONFIRMAR_DESMARCACAO = "confirmar_desmarcacao"
    RESPONDER_SOLICITACAO = "responder_solicitacao"


PERGUNTAS_QUE_ALTERAM_A_AGENDA = frozenset({
    Pergunta.CONFIRMAR_HORARIO, Pergunta.CONFIRMAR_TROCA, Pergunta.CONFIRMAR_DESMARCACAO,
    Pergunta.RESPONDER_SOLICITACAO,
})


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
    proposta: str | None = Field(default=None, pattern=TOKEN_DE_PROPOSTA)
    origem: str | None = Field(default=None, max_length=40)
    horario_id: int | None = Field(default=None, gt=0)
    consulta_id: int | None = Field(default=None, gt=0)
    notificacao_id: int | None = None
    solicitacao: Literal["remarcacao", "cancelamento"] | None = None
    criterios: CriteriosAgendamento = Field(default_factory=CriteriosAgendamento)
    # O pedido original e os avisos permitem reapresentar "fora do período pedido" na retomada.
    pedido: CriteriosAgendamento | None = None
    avisos: list[str] = Field(default_factory=list, max_length=6)
    recusados: list[int] = Field(default_factory=list, max_length=120)
    horarios_oferecidos: list[int] = Field(default_factory=list, max_length=6)
    aguardando_escolha: bool = False
    duvida_opcao: int | None = Field(default=None, ge=1, le=6)
    duvida_dia: date | None = None
    etapa_remarcacao: Literal["origem", "destino"] | None = None
    consultas_oferecidas: list[int] = Field(default_factory=list, max_length=6)
    origem_horario_id: int | None = Field(default=None, gt=0)
    pagina_consultas: int = Field(default=0, ge=0, le=1000)

    @property
    def pergunta(self) -> Pergunta:
        if self.tipo == TipoAcao.RESPONDER_SOLICITACAO:
            return Pergunta.RESPONDER_SOLICITACAO
        if self.tipo == TipoAcao.CANCELAR:
            return Pergunta.CONFIRMAR_DESMARCACAO if self.consulta_id else Pergunta.ESCOLHER_CONSULTA
        if self.tipo == TipoAcao.GERENCIAR:
            return Pergunta.ESCOLHER_ACAO if self.consulta_id else Pergunta.ESCOLHER_CONSULTA
        if self.tipo == TipoAcao.REMARCAR and self.etapa_remarcacao == "origem":
            return Pergunta.ESCOLHER_CONSULTA
        if self.aguardando_escolha:
            return Pergunta.ESCOLHER_HORARIO
        if self.horario_id:
            return Pergunta.CONFIRMAR_TROCA if self.tipo == TipoAcao.REMARCAR else Pergunta.CONFIRMAR_HORARIO
        return Pergunta.INFORMAR_DESTINO if self.tipo == TipoAcao.REMARCAR else Pergunta.NOVA_BUSCA

    @computed_field
    @property
    def confirmacao_pendente(self) -> bool:
        """O front-end usa este sinal para orientar o paciente quando a conexão cai após confirmar."""
        return self.pergunta in PERGUNTAS_QUE_ALTERAM_A_AGENDA

    def sem_proposta(self) -> dict[str, Any]:
        return self.model_dump(exclude={"proposta"})


class ContextoConversa(BaseModel):
    preferencia_estilo: Literal["automatico", "padrao", "simplificado"] = "automatico"
    estilo: EstiloComunicacao | None = None
    opcoes_por_vez: int | None = Field(default=None, ge=1, le=6)
    # Evidência do classificador cifrada pelo backend: opaca para o front-end e para o paciente.
    estado_estilo: str | None = Field(default=None, max_length=512)
    acao_pendente: AcaoPendente | None = None
    solicitacoes_vistas: list[int] = Field(default_factory=list, max_length=120)


CodigoDeBotao = Literal[
    "confirmar_horario", "confirmar_troca", "desmarcar_consulta", "manter_consulta", "nao_marcar",
    "outro_horario", "escolher", "buscar_dia", "buscar_horarios", "mudar_horario", "desmarcar_esta",
    "marcar_consulta", "minhas_consultas", "mudar_ou_cancelar",
]


class AcaoDeBotao(BaseModel):
    codigo: CodigoDeBotao
    proposta: str | None = Field(default=None, pattern=TOKEN_DE_PROPOSTA)
    valor: str | None = Field(default=None, max_length=20, pattern=r"^[0-9-]+$")


class OpcaoDeResposta(BaseModel):
    codigo: CodigoDeBotao
    rotulo: str
    proposta: str | None = None
    valor: str | None = None


class ChatRequest(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    mensagem: str = Field(..., min_length=1, max_length=500)
    acao: AcaoDeBotao | None = None
    contexto: ContextoConversa = Field(default_factory=ContextoConversa)


class RetomadaRequest(BaseModel):
    contexto: ContextoConversa = Field(default_factory=ContextoConversa)


class ChatResponse(BaseModel):
    """Sem perfil etário, probabilidade ou heurísticas: o paciente não é rotulado pela interface."""

    modo_degradado: bool = False
    resposta: str
    estilo: EstiloComunicacao
    opcoes: list[OpcaoDeResposta] = Field(default_factory=list)
    intencao: str
    resultado: str
    entidades: dict[str, Any]
    contexto: ContextoConversa
    consulta: ConsultaDetalhadaOut | None = None
