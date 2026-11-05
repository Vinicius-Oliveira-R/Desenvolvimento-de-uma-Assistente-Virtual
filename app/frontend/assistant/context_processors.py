from django.http import HttpRequest

from assistant.perfis import EQUIPE, EQUIPE_CLINICA, ROTULOS
from assistant.session import SessaoAssistente


def perfil(request: HttpRequest) -> dict[str, object]:
    papel = request.session.get(SessaoAssistente.PAPEL) if hasattr(request, "session") else None
    return {
        "area_da_equipe": papel in EQUIPE,
        "gerencia_consultas": papel in EQUIPE_CLINICA,
        "papel_rotulo": ROTULOS.get(papel, "Paciente"),
    }
