import pytest

from app.backend.models import PapelUsuario
from app.backend.tests.helpers import SENHA_PADRAO, ClinicaApi


def _liberacao(medico_id: int, **ajustes: object) -> dict[str, object]:
    return {
        "medico_id": medico_id,
        "data_inicio": "2026-11-09",
        "data_fim": "2026-11-13",
        "dias_semana": [0, 2],
        "hora_inicio": "08:00",
        "hora_fim": "10:00",
        "duracao_minutos": 30,
        **ajustes,
    }


def test_liberacao_cria_horarios_nos_dias_e_faixas_pedidos_sem_duplicar(api: ClinicaApi) -> None:
    medico = api.cadastrar_medico("Dr. João Mendes", "CRM-SP-1", "Cardiologia")

    primeira = api.client.post("/api/horarios/lote", headers=api.admin, json=_liberacao(medico)).json()
    repetida = api.client.post("/api/horarios/lote", headers=api.admin, json=_liberacao(medico)).json()

    assert primeira == {"criados": 8, "ja_existentes": 0}
    assert repetida == {"criados": 0, "ja_existentes": 8}
    quarta = api.client.get("/api/horarios", params={"medico_id": medico, "data": "2026-11-11"}).json()
    assert [(h["hora_inicio"], h["hora_fim"]) for h in quarta] == [
        ("08:00", "08:30"), ("08:30", "09:00"), ("09:00", "09:30"), ("09:30", "10:00")
    ]
    assert api.client.get("/api/horarios", params={"medico_id": medico, "data": "2026-11-10"}).json() == []


def test_liberacao_recusa_datas_passadas_e_periodos_longos(api: ClinicaApi) -> None:
    medico = api.cadastrar_medico("Dr. João Mendes", "CRM-SP-1", "Cardiologia")

    def liberar(**ajustes: str) -> int:
        return api.client.post("/api/horarios/lote", headers=api.admin, json=_liberacao(medico, **ajustes)).status_code

    assert liberar(data_inicio="2026-11-02") == 400
    assert liberar(data_fim="2027-03-01") == 422


@pytest.mark.parametrize(
    ("papel", "status"),
    [(PapelUsuario.ADMIN, 201), (PapelUsuario.MEDICO, 201), (PapelUsuario.GESTOR, 403), (PapelUsuario.PACIENTE, 403)],
)
def test_somente_recepcao_e_medico_liberam_horarios(api: ClinicaApi, papel: PapelUsuario, status: int) -> None:
    medico = api.cadastrar_medico("Dr. João Mendes", "CRM-SP-1", "Cardiologia")
    headers = api.criar_usuario_no_banco("Fulano", f"{papel}.horarios@email.com", papel)

    assert api.client.post("/api/horarios/lote", headers=headers, json=_liberacao(medico)).status_code == status
    assert api.client.post("/api/horarios/lote", json=_liberacao(medico)).status_code == 401


def test_medico_cadastrado_com_ficha_enxerga_a_propria_agenda(api: ClinicaApi) -> None:
    ficha = {"crm": "CRM-SP-777", "especialidade": "Neurologia"}
    api.client.post(
        "/api/auth/register",
        headers=api.medico,
        json={
            "nome": "Dr. Rafael Teixeira", "email": "rafael@email.com", "senha": SENHA_PADRAO,
            "papel": "medico", "medico": ficha,
        },
    )
    sessao = api.client.post("/api/auth/login", json={"email": "rafael@email.com", "senha": SENHA_PADRAO}).json()
    rafael = {"Authorization": f"Bearer {sessao['token']}"}

    perfil = api.client.get("/api/auth/me", headers=rafael).json()
    ficha_criada = next(m for m in api.client.get("/api/medicos").json() if m["crm"] == "CRM-SP-777")
    assert perfil["medico_id"] == ficha_criada["id"]

    _, paciente = api.cadastrar_paciente("Lurdes Andrade", "lurdes@email.com", "12345678901")
    horario = api.cadastrar_horario(perfil["medico_id"], "2026-11-10", "09:00")
    api.client.post(
        "/api/consultas",
        headers=rafael,
        json={"paciente_id": paciente, "medico_id": perfil["medico_id"], "horario_id": horario, "data": "2026-11-10"},
    )
    agenda = api.client.get(
        "/api/consultas", headers=rafael, params={"medico_id": perfil["medico_id"], "data_inicio": "2026-11-10"}
    ).json()
    assert [c["paciente_nome"] for c in agenda] == ["Lurdes Andrade"]


def test_usuario_que_nao_e_medico_nao_tem_ficha_vinculada(api: ClinicaApi) -> None:
    assert api.client.get("/api/auth/me", headers=api.admin).json()["medico_id"] is None
