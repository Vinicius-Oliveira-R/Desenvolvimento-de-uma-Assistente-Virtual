import pytest
from sqlalchemy.exc import IntegrityError

from app.backend.core.database import SessionLocal
from app.backend.models import PapelUsuario, Usuario
from app.backend.tests.helpers import SENHA_PADRAO, ClinicaApi

GESTOR, ADMIN, MEDICO, PACIENTE = PapelUsuario.GESTOR, PapelUsuario.ADMIN, PapelUsuario.MEDICO, PapelUsuario.PACIENTE
NOVO_MEDICO = {"nome": "Dra. Nova", "crm": "CRM-SP-9999", "especialidade": "Cardiologia"}


def _logado_como(api: ClinicaApi, papel: PapelUsuario | None) -> dict[str, str]:
    return api.criar_usuario_no_banco(f"Usuário {papel}", f"{papel}.solicitante@email.com", papel) if papel else {}


def _dados_de_paciente(usuario_id: int, cpf: str = "12345678909") -> dict[str, object]:
    return {
        "usuario_id": usuario_id,
        "nome": "Paciente Novo",
        "cpf": cpf,
        "data_nascimento": "1950-03-10",
        "telefone": "11999990000",
    }


@pytest.mark.parametrize(
    ("solicitante", "papel_novo", "status"),
    [
        (GESTOR, MEDICO, 201),
        (GESTOR, ADMIN, 201),
        (GESTOR, PACIENTE, 403),
        (ADMIN, PACIENTE, 201),
        (ADMIN, ADMIN, 201),
        (ADMIN, MEDICO, 403),
        (MEDICO, PACIENTE, 201),
        (MEDICO, ADMIN, 201),
        (MEDICO, MEDICO, 201),
        (PACIENTE, PACIENTE, 403),
        (PACIENTE, ADMIN, 403),
        (None, ADMIN, 401),
    ],
)
def test_cadastro_de_usuarios_segue_a_matriz_de_permissoes(
    api: ClinicaApi, solicitante: PapelUsuario | None, papel_novo: PapelUsuario, status: int
) -> None:
    resposta = api.client.post(
        "/api/auth/register",
        headers=_logado_como(api, solicitante),
        json={"nome": "Novo Usuário", "email": "novo@email.com", "senha": SENHA_PADRAO, "papel": papel_novo},
    )

    assert resposta.status_code == status, resposta.text
    if status == 201:
        assert resposta.json()["papel"] == papel_novo
        assert "token" not in resposta.json()


@pytest.mark.parametrize("solicitante", list(PapelUsuario))
def test_ninguem_cadastra_usuario_com_o_papel_de_gestor(api: ClinicaApi, solicitante: PapelUsuario) -> None:
    resposta = api.client.post(
        "/api/auth/register",
        headers=_logado_como(api, solicitante),
        json={"nome": "Outro Gestor", "email": "outro.gestor@email.com", "senha": SENHA_PADRAO, "papel": GESTOR},
    )

    assert resposta.status_code == 403, resposta.text


@pytest.mark.parametrize(
    ("solicitante", "status"), [(MEDICO, 201), (GESTOR, 201), (ADMIN, 403), (PACIENTE, 403), (None, 401)]
)
def test_somente_medico_e_gestor_cadastram_medico(
    api: ClinicaApi, solicitante: PapelUsuario | None, status: int
) -> None:
    resposta = api.client.post("/api/medicos", headers=_logado_como(api, solicitante), json=NOVO_MEDICO)

    assert resposta.status_code == status, resposta.text


@pytest.mark.parametrize(
    ("solicitante", "status"), [(ADMIN, 201), (MEDICO, 201), (GESTOR, 403), (PACIENTE, 403), (None, 401)]
)
def test_atendente_e_medico_cadastram_paciente(api: ClinicaApi, solicitante: PapelUsuario | None, status: int) -> None:
    usuario = api.cadastrar_usuario("Paciente Novo", "paciente.novo@email.com")

    resposta = api.client.post(
        "/api/pacientes", headers=_logado_como(api, solicitante), json=_dados_de_paciente(usuario["id"])
    )

    assert resposta.status_code == status, resposta.text


def test_cadastro_de_paciente_exige_usuario_paciente_sem_cadastro_e_cpf_inedito(api: ClinicaApi) -> None:
    medico = api.cadastrar_usuario("Dr. Fulano", "fulano@email.com", MEDICO)
    paciente = api.cadastrar_usuario("Paciente", "paciente@email.com")
    outro = api.cadastrar_usuario("Outro Paciente", "outro@email.com")

    def vincular(usuario_id: int, cpf: str) -> int:
        resposta = api.client.post("/api/pacientes", headers=api.admin, json=_dados_de_paciente(usuario_id, cpf))
        return resposta.status_code

    assert vincular(medico["id"], "10001234560") == 400
    assert vincular(paciente["id"], "10002469065") == 201
    assert vincular(paciente["id"], "10003703568") == 409
    assert vincular(outro["id"], "10002469065") == 409
    assert vincular(9999, "10004938062") == 404


def test_lista_de_pacientes_com_dados_pessoais_e_restrita_a_funcionarios(api: ClinicaApi) -> None:
    headers_paciente, _ = api.cadastrar_paciente("Lurdes Andrade", "lurdes@email.com", "10006172547")

    assert api.client.get("/api/pacientes").status_code == 401
    assert api.client.get("/api/pacientes", headers=headers_paciente).status_code == 403
    assert api.client.get("/api/pacientes", headers=_logado_como(api, GESTOR)).status_code == 403
    assert api.client.get("/api/pacientes", headers=api.admin).status_code == 200


def test_papel_e_conferido_no_banco_a_cada_requisicao(api: ClinicaApi) -> None:
    medico = api.cadastrar_usuario("Dr. Rebaixado", "rebaixado@email.com", MEDICO)
    headers = api.cabecalho_de(medico["id"])
    assert api.client.get("/api/pacientes", headers=headers).status_code == 200

    api.definir_papel(medico["id"], PACIENTE)

    assert api.client.get("/api/pacientes", headers=headers).status_code == 403


def test_login_e_perfil_atual_informam_o_papel(api: ClinicaApi) -> None:
    api.cadastrar_usuario("Dr. Fulano", "fulano@email.com", MEDICO)

    sessao = api.client.post("/api/auth/login", json={"email": "fulano@email.com", "senha": SENHA_PADRAO}).json()
    perfil = api.client.get("/api/auth/me", headers={"Authorization": f"Bearer {sessao['token']}"}).json()

    assert sessao["papel"] == perfil["papel"] == "medico"


def test_banco_recusa_papel_fora_dos_perfis_definidos(banco_limpo: None) -> None:
    with SessionLocal() as db, pytest.raises(IntegrityError):
        db.add(Usuario(nome="Intruso", email="intruso@email.com", senha_hash="x", papel="superadmin"))
        db.commit()
