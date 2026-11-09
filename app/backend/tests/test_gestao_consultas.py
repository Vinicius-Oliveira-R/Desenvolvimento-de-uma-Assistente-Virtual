import pytest

from app.backend.models import PapelUsuario
from app.backend.tests.helpers import ClinicaApi


def _clinica(api: ClinicaApi) -> dict[str, int]:
    _, lurdes = api.cadastrar_paciente("Lurdes Andrade", "lurdes@email.com", "12345678901")
    joao = api.cadastrar_medico("Dr. João Mendes", "CRM-SP-1", "Cardiologia")
    maria = api.cadastrar_medico("Dra. Maria Silva", "CRM-SP-2", "Clínica Geral")
    return {
        "lurdes": lurdes,
        "joao": joao,
        "maria": maria,
        "joao_dia_10": api.cadastrar_horario(joao, "2026-11-10", "09:00"),
        "joao_dia_12": api.cadastrar_horario(joao, "2026-11-12", "10:00"),
        "maria_dia_11": api.cadastrar_horario(maria, "2026-11-11", "14:00"),
    }


def _agendar(api: ClinicaApi, headers: dict[str, str], paciente: int, medico: int, horario: int, data: str):
    return api.client.post(
        "/api/consultas",
        headers=headers,
        json={"paciente_id": paciente, "medico_id": medico, "horario_id": horario, "data": data},
    )


@pytest.mark.parametrize(
    ("papel", "status"),
    [(PapelUsuario.ADMIN, 200), (PapelUsuario.MEDICO, 200), (PapelUsuario.GESTOR, 403), (PapelUsuario.PACIENTE, 403)],
)
def test_somente_recepcao_e_medico_acessam_a_agenda(api: ClinicaApi, papel: PapelUsuario, status: int) -> None:
    headers = api.criar_usuario_no_banco("Fulano", f"{papel}.agenda@email.com", papel)

    assert api.client.get("/api/consultas", headers=headers).status_code == status


def test_agenda_sem_login_e_recusada(api: ClinicaApi) -> None:
    assert api.client.get("/api/consultas").status_code == 401


def test_paciente_nao_agenda_pela_api_da_equipe(api: ClinicaApi) -> None:
    ids = _clinica(api)
    paciente = api.cabecalho_de(api.cadastrar_usuario("Beto", "beto@email.com")["id"])

    resposta = _agendar(api, paciente, ids["lurdes"], ids["joao"], ids["joao_dia_10"], "2026-11-10")

    assert resposta.status_code == 403


def test_agenda_traz_paciente_e_medico_e_aceita_filtros(api: ClinicaApi) -> None:
    ids = _clinica(api)
    _agendar(api, api.medico, ids["lurdes"], ids["joao"], ids["joao_dia_10"], "2026-11-10")
    _agendar(api, api.admin, ids["lurdes"], ids["maria"], ids["maria_dia_11"], "2026-11-11")

    agenda = api.client.get("/api/consultas", headers=api.admin).json()
    do_joao = api.client.get("/api/consultas", headers=api.admin, params={"medico_id": ids["joao"]}).json()
    do_dia_11 = api.client.get(
        "/api/consultas", headers=api.admin, params={"data_inicio": "2026-11-11", "data_fim": "2026-11-11"}
    ).json()

    assert [(c["paciente_nome"], c["medico_nome"], c["data"], c["hora_inicio"]) for c in agenda] == [
        ("Lurdes Andrade", "Dr. João Mendes", "2026-11-10", "09:00"),
        ("Lurdes Andrade", "Dra. Maria Silva", "2026-11-11", "14:00"),
    ]
    assert [c["medico_nome"] for c in do_joao] == ["Dr. João Mendes"]
    assert [c["data"] for c in do_dia_11] == ["2026-11-11"]


def test_recepcao_remarca_e_medico_cancela_liberando_os_horarios(api: ClinicaApi) -> None:
    ids = _clinica(api)
    consulta = _agendar(api, api.admin, ids["lurdes"], ids["joao"], ids["joao_dia_10"], "2026-11-10").json()["id"]

    remarcada = api.client.put(
        f"/api/consultas/{consulta}", headers=api.admin, json={"horario_id": ids["joao_dia_12"], "confirmado": True}
    )
    assert remarcada.status_code == 200
    assert api.horario_disponivel(ids["joao_dia_10"])
    assert not api.horario_disponivel(ids["joao_dia_12"])

    detalhe = api.client.get(f"/api/consultas/{consulta}", headers=api.medico).json()
    assert (detalhe["data"], detalhe["hora_inicio"], detalhe["paciente_nome"]) == (
        "2026-11-12", "10:00", "Lurdes Andrade"
    )

    cancelada = api.client.request(
        "DELETE", f"/api/consultas/{consulta}", headers=api.medico, json={"confirmado": True}
    )
    assert cancelada.json()["status"] == "cancelada"
    assert api.horario_disponivel(ids["joao_dia_12"])
    situacao = api.client.get("/api/consultas", headers=api.admin, params={"status": "cancelada"}).json()
    assert [c["id"] for c in situacao] == [consulta]


def test_horarios_podem_ser_filtrados_por_medico_data_e_disponibilidade(api: ClinicaApi) -> None:
    ids = _clinica(api)
    _agendar(api, api.admin, ids["lurdes"], ids["joao"], ids["joao_dia_10"], "2026-11-10")

    livres_do_joao = api.client.get("/api/horarios", params={"medico_id": ids["joao"], "disponivel": True}).json()
    do_dia_10 = api.client.get("/api/horarios", params={"medico_id": ids["joao"], "data": "2026-11-10"}).json()

    assert [h["id"] for h in livres_do_joao] == [ids["joao_dia_12"]]
    assert [(h["id"], h["disponivel"]) for h in do_dia_10] == [(ids["joao_dia_10"], False)]
