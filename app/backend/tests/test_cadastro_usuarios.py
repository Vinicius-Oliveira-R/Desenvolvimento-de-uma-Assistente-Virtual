import pytest

from app.backend.models import PapelUsuario
from app.backend.tests.helpers import SENHA_PADRAO, ClinicaApi

FICHA_PACIENTE = {"cpf": "12345678900", "data_nascimento": "1948-05-12", "telefone": "11999990000"}


def _cadastrar(api: ClinicaApi, headers: dict[str, str], **dados: object) -> tuple[int, dict]:
    resposta = api.client.post("/api/auth/register", headers=headers, json={"senha": SENHA_PADRAO, **dados})
    return resposta.status_code, resposta.json()


def test_paciente_e_sua_ficha_sao_cadastrados_em_uma_unica_requisicao(api: ClinicaApi) -> None:
    status, usuario = _cadastrar(
        api, api.admin, nome="Lurdes Andrade", email="lurdes@email.com", papel="paciente", paciente=FICHA_PACIENTE
    )

    assert status == 201
    pacientes = api.client.get("/api/pacientes", headers=api.admin).json()
    resumo = [(p["usuario_id"], p["nome"], p["cpf"]) for p in pacientes]
    assert resumo == [(usuario["id"], "Lurdes Andrade", "12345678900")]


def test_cpf_repetido_nao_deixa_usuario_sem_ficha(api: ClinicaApi) -> None:
    _cadastrar(
        api, api.admin, nome="Lurdes Andrade", email="lurdes@email.com", papel="paciente", paciente=FICHA_PACIENTE
    )

    status, erro = _cadastrar(
        api, api.admin, nome="Outra Pessoa", email="outra@email.com", papel="paciente", paciente=FICHA_PACIENTE
    )

    assert (status, erro["detail"]) == (409, "Já existe um paciente com este CPF")
    login = api.client.post("/api/auth/login", json={"email": "outra@email.com", "senha": SENHA_PADRAO})
    assert login.status_code == 401


def test_medico_e_sua_ficha_profissional_sao_cadastrados_juntos(api: ClinicaApi) -> None:
    ficha = {"crm": "CRM-SP-123456", "especialidade": "Cardiologia"}

    status, _ = _cadastrar(
        api, api.medico, nome="Dra. Helena Prado", email="helena@email.com", papel="medico", medico=ficha
    )

    assert status == 201
    medicos = api.client.get("/api/medicos").json()
    assert {"nome": "Dra. Helena Prado", **ficha}.items() <= medicos[0].items()
    status_da_copia, _ = _cadastrar(
        api, api.medico, nome="Dr. Copia", email="copia@email.com", papel="medico", medico=ficha
    )
    assert status_da_copia == 409


def test_ficha_precisa_combinar_com_o_papel_do_usuario(api: ClinicaApi) -> None:
    status, _ = _cadastrar(
        api, api.admin, nome="Atendente", email="at@email.com", papel="admin", paciente=FICHA_PACIENTE
    )

    assert status == 422


@pytest.mark.parametrize(
    ("papel", "cadastraveis"),
    [
        (PapelUsuario.GESTOR, ["admin", "medico"]),
        (PapelUsuario.ADMIN, ["admin", "paciente"]),
        (PapelUsuario.MEDICO, ["admin", "medico", "paciente"]),
        (PapelUsuario.PACIENTE, []),
    ],
)
def test_perfil_informa_os_papeis_que_o_usuario_pode_cadastrar(
    api: ClinicaApi, papel: PapelUsuario, cadastraveis: list[str]
) -> None:
    headers = api.criar_usuario_no_banco("Fulano", f"{papel}.perfil@email.com", papel)

    perfil = api.client.get("/api/auth/me", headers=headers).json()

    assert (perfil["papel"], perfil["papeis_cadastraveis"]) == (papel, cadastraveis)


def test_especialidades_do_catalogo_do_assistente_sao_publicas(api: ClinicaApi) -> None:
    especialidades = api.client.get("/api/medicos/especialidades").json()

    assert {"Cardiologia", "Clínica Geral", "Ortopedia"} <= set(especialidades)


def test_crm_repetido_na_rota_de_medicos_e_conflito(api: ClinicaApi) -> None:
    api.cadastrar_medico("Dr. João", "CRM-SP-1", "Cardiologia")

    resposta = api.client.post(
        "/api/medicos", headers=api.medico, json={"nome": "Dr. Outro", "crm": "CRM-SP-1", "especialidade": "Ortopedia"}
    )

    assert resposta.status_code == 409
