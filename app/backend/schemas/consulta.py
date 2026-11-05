from pydantic import BaseModel, ConfigDict, Field

from app.backend.models import Consulta, Horario, Medico, Paciente, StatusConsulta


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
    status: StatusConsulta | None = None
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


class ConsultaDetalhadaOut(BaseModel):
    id: int
    status: str
    data: str
    hora_inicio: str
    hora_fim: str
    medico_id: int
    medico_nome: str
    especialidade: str
    observacao: str | None = None

    @classmethod
    def from_models(cls, consulta: Consulta, horario: Horario, medico: Medico) -> "ConsultaDetalhadaOut":
        return cls(
            id=consulta.id,
            status=consulta.status,
            data=horario.data,
            hora_inicio=horario.hora_inicio,
            hora_fim=horario.hora_fim,
            medico_id=medico.id,
            medico_nome=medico.nome,
            especialidade=medico.especialidade,
            observacao=consulta.observacao,
        )


class ConsultaAgendaOut(ConsultaDetalhadaOut):
    horario_id: int
    paciente_id: int
    paciente_nome: str

    @classmethod
    def from_agenda(
        cls, consulta: Consulta, horario: Horario, medico: Medico, paciente: Paciente
    ) -> "ConsultaAgendaOut":
        detalhada = ConsultaDetalhadaOut.from_models(consulta, horario, medico)
        return cls(
            **detalhada.model_dump(), horario_id=horario.id, paciente_id=paciente.id, paciente_nome=paciente.nome
        )
