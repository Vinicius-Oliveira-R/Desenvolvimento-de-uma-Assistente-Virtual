from django.shortcuts import resolve_url

PACIENTE = "paciente"
EQUIPE = frozenset({"gestor", "admin", "medico"})
EQUIPE_CLINICA = frozenset({"admin", "medico"})
ROTULOS = {"gestor": "Gestor", "admin": "Atendente", "medico": "Médico", PACIENTE: "Paciente"}


def pagina_inicial(papel: str) -> str:
    return resolve_url("equipe" if papel in EQUIPE else "chat")
