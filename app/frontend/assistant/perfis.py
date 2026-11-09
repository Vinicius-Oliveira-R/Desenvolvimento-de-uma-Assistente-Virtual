from django.shortcuts import resolve_url

PACIENTE = "paciente"
EQUIPE = frozenset({"gestor", "admin", "medico"})
EQUIPE_CLINICA = frozenset({"admin", "medico"})
ROTULOS = {"gestor": "Gestor", "admin": "Atendente", "medico": "Médico", PACIENTE: "Paciente"}


MEDICO = "medico"
TODOS = EQUIPE | {PACIENTE}


def pagina_inicial(papel: str) -> str:
    if papel == MEDICO:
        return resolve_url("agenda_medica")
    return resolve_url("equipe" if papel in EQUIPE else "chat")
