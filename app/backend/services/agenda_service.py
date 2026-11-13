import re
from collections.abc import Sequence
from datetime import date

from sqlalchemy.orm import Session

from app.backend.assistant.especialidades import buscar_especialidade
from app.backend.assistant.patterns import TITULOS_MEDICOS
from app.backend.assistant.temporal import TURNOS
from app.backend.core.clock import Clock
from app.backend.core.text import normalizar
from app.backend.models import Horario, Medico
from app.backend.repositories.horario_repository import FiltroHorarios, HorarioRepository
from app.backend.repositories.medico_repository import MedicoRepository


def _palavras_do_nome(nome: str) -> set[str]:
    return set(re.findall(r"[a-z]+", normalizar(nome))) - {titulo.rstrip(".") for titulo in TITULOS_MEDICOS}


class AgendaService:
    def __init__(self, db: Session, clock: Clock):
        self.clock = clock
        self.medicos = MedicoRepository(db)
        self.horarios = HorarioRepository(db)

    def find_doctors_by_name(self, nome: str) -> list[Medico]:
        procuradas = _palavras_do_nome(nome)
        if not procuradas:
            return []
        return [medico for medico in self.medicos.list_active() if procuradas <= _palavras_do_nome(medico.nome)]

    def find_doctors_by_specialty(self, especialidade: str) -> list[Medico]:
        catalogada = buscar_especialidade(especialidade)
        alvo = normalizar(catalogada.nome if catalogada else especialidade)
        return [medico for medico in self.medicos.list_active() if normalizar(medico.especialidade) == alvo]

    def find_slot(self, medico_id: int, data: date, hora: str) -> Horario | None:
        return self.horarios.find_slot(medico_id, data.isoformat(), hora)

    def is_future(self, horario: Horario) -> bool:
        agora = self.clock.now()
        return (horario.data, horario.hora_inicio) > (agora.date().isoformat(), agora.strftime("%H:%M"))

    def next_available(
        self,
        medico_ids: Sequence[int],
        *,
        data_inicio: date | None = None,
        data_fim: date | None = None,
        hora: str | None = None,
        turno: str | None = None,
        excluir: Sequence[int] = (),
        limite: int = 1,
    ) -> list[Horario]:
        agora = self.clock.now()
        hoje = agora.date()
        inicio = max(data_inicio or hoje, hoje)
        filtro = FiltroHorarios(
            medico_ids=tuple(medico_ids),
            apos_data=inicio.isoformat(),
            apos_hora=agora.strftime("%H:%M") if inicio == hoje else "",
            ate_data=data_fim.isoformat() if data_fim else None,
            faixa_horaria=TURNOS.get(turno) if turno else None,
            hora_exata=hora,
            excluir_ids=tuple(excluir),
        )
        return self.horarios.search_available(filtro, limite)
