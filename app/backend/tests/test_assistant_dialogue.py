import pytest

from app.backend.tests.helpers import ClinicaApi


def _paciente_com_agenda(api: ClinicaApi) -> tuple[dict[str, str], list[int]]:
    headers, _ = api.cadastrar_paciente("Lurdes Andrade", "lurdes@email.com", "55555555555")
    medico = api.cadastrar_medico("Dr. João Mendes", "CRM-SP-1001", "Cardiologia")
    horarios = [
        api.cadastrar_horario(medico, data, hora)
        for data, hora in (("2026-11-10", "09:00"), ("2026-11-10", "10:00"), ("2026-11-12", "14:00"))
    ]
    return headers, horarios


def test_paciente_pede_outro_horario_e_depois_desiste(api: ClinicaApi) -> None:
    headers, horarios = _paciente_com_agenda(api)
    conversa = api.conversa(headers)

    primeira = conversa.enviar("Quero agendar cardiologista na próxima semana")
    segunda = conversa.enviar("outro")
    desistencia = conversa.enviar("não")

    assert primeira["contexto"]["acao_pendente"]["horario_id"] == horarios[0]
    assert segunda["contexto"]["acao_pendente"]["horario_id"] == horarios[1]
    assert desistencia["intencao"] == "negar"
    assert desistencia["resultado"] == "agendamento_descartado"
    assert desistencia["contexto"]["acao_pendente"] is None
    assert all(api.horario_disponivel(horario) for horario in horarios)


def test_recusa_com_nova_data_refaz_a_busca_mantendo_a_especialidade(api: ClinicaApi) -> None:
    headers, horarios = _paciente_com_agenda(api)
    conversa = api.conversa(headers)

    conversa.enviar("Quero agendar cardiologista na próxima semana")
    nova_busca = conversa.enviar("não, prefiro dia 12/11")

    assert nova_busca["resultado"] == "sugestao_horario"
    assert nova_busca["contexto"]["acao_pendente"]["horario_id"] == horarios[2]


def test_medico_inexistente_e_informado(api: ClinicaApi) -> None:
    headers, _ = _paciente_com_agenda(api)

    resposta = api.conversa(headers).enviar("Quero agendar com Dr. Fulano amanhã às 10h")

    assert resposta["resultado"] == "medico_nao_encontrado"


def test_paciente_lista_proximas_consultas(api: ClinicaApi) -> None:
    headers, _ = _paciente_com_agenda(api)
    conversa = api.conversa(headers)
    conversa.enviar("Quero agendar com Dr. João dia 12/11 às 14h")

    resposta = conversa.enviar("quais são minhas consultas?")

    assert resposta["resultado"] == "lista_consultas"
    assert "12/11/2026 às 14:00 — Dr. João Mendes (Cardiologia)" in resposta["resposta"]


def _paciente_com_clinico_e_ortopedista(api: ClinicaApi) -> tuple[dict[str, str], dict[str, int]]:
    headers, _ = api.cadastrar_paciente("Lurdes Andrade", "lurdes@email.com", "55555555555")
    medicos = {
        "Clínica Geral": api.cadastrar_medico("Dra. Maria Silva", "CRM-SP-2002", "Clínica Geral"),
        "Ortopedia": api.cadastrar_medico("Dr. Carlos Lima", "CRM-SP-3003", "Ortopedia"),
    }
    horarios = {
        especialidade: api.cadastrar_horario(medico, "2026-11-10", "09:00") for especialidade, medico in medicos.items()
    }
    return headers, horarios


def test_pedido_sem_especialidade_recebe_pergunta_simples_que_oferece_clinico_geral(api: ClinicaApi) -> None:
    headers, _ = _paciente_com_clinico_e_ortopedista(api)

    resposta = api.conversa(headers).enviar("marcar consulta")

    assert resposta["perfil"] == "IDOSO"
    assert resposta["resultado"] == "falta_especialidade"
    assert "Se não souber, posso marcar com um clínico geral. Pode ser?" in resposta["resposta"]
    assert "1." not in resposta["resposta"]


def test_paciente_padrao_mantem_a_pergunta_tecnica_de_especialidade(api: ClinicaApi) -> None:
    headers, _ = _paciente_com_clinico_e_ortopedista(api)

    resposta = api.conversa(headers).enviar("Quero agendar uma consulta para amanhã às 10h, por favor.")

    assert resposta["perfil"] == "PADRAO"
    assert resposta["resultado"] == "falta_especialidade"
    assert resposta["resposta"].startswith("Para qual especialidade ou médico deseja agendar?")


@pytest.mark.parametrize(
    ("mensagens", "especialidade"),
    [
        (["quero marcar uma consulta para ver minha dor nas costas"], "Ortopedia"),
        (["marcar consulta", "dor nas costas"], "Ortopedia"),
        (["quero marcar com qualquer médico"], "Clínica Geral"),
        (["marcar consulta", "não sei"], "Clínica Geral"),
        (["marcar consulta", "geral"], "Clínica Geral"),
        (["marcar consulta", "qualquer um"], "Clínica Geral"),
        (["marcar consulta", "pode ser"], "Clínica Geral"),
        (["marcar consulta", "estou com dor no dedo do pé"], "Clínica Geral"),
        (["marcar consulta", "quero marcar consulta"], "Clínica Geral"),
    ],
)
def test_assistente_sugere_horario_sem_repetir_a_pergunta_de_especialidade(
    api: ClinicaApi, mensagens: list[str], especialidade: str
) -> None:
    headers, horarios = _paciente_com_clinico_e_ortopedista(api)
    conversa = api.conversa(headers)

    respostas = [conversa.enviar(mensagem) for mensagem in mensagens]

    assert respostas[-1]["resultado"] == "sugestao_horario"
    assert respostas[-1]["contexto"]["acao_pendente"]["horario_id"] == horarios[especialidade]


def test_paciente_que_nao_sabe_a_especialidade_conclui_o_agendamento_com_clinico_geral(api: ClinicaApi) -> None:
    headers, horarios = _paciente_com_clinico_e_ortopedista(api)
    conversa = api.conversa(headers)

    conversa.enviar("quero marcar uma consulta")
    conversa.enviar("não sei")
    confirmacao = conversa.enviar("sim")

    assert confirmacao["resultado"] == "consulta_agendada"
    assert confirmacao["consulta"]["especialidade"] == "Clínica Geral"
    assert not api.horario_disponivel(horarios["Clínica Geral"])


@pytest.mark.parametrize(
    ("mensagem", "resultado"), [("não", "agendamento_descartado"), ("quais são minhas consultas?", "sem_consultas")]
)
def test_pergunta_de_especialidade_respeita_desistencia_e_mudanca_de_assunto(
    api: ClinicaApi, mensagem: str, resultado: str
) -> None:
    headers, _ = _paciente_com_clinico_e_ortopedista(api)
    conversa = api.conversa(headers)
    conversa.enviar("marcar consulta")

    resposta = conversa.enviar(mensagem)

    assert resposta["resultado"] == resultado
    assert resposta["contexto"]["acao_pendente"] is None


def test_usuario_sem_cadastro_de_paciente_e_orientado(api: ClinicaApi) -> None:
    token = api.client.post(
        "/api/auth/register", json={"nome": "Sem Cadastro", "email": "sem@email.com", "senha": "senha123"}
    ).json()["token"]

    resposta = api.conversa({"Authorization": f"Bearer {token}"}).enviar("Quero marcar uma consulta")

    assert resposta["resultado"] == "paciente_nao_cadastrado"


def test_senha_acima_do_limite_do_bcrypt_e_rejeitada(api: ClinicaApi) -> None:
    resposta = api.client.post(
        "/api/auth/register", json={"nome": "Ana", "email": "ana@email.com", "senha": "ç" * 37}
    )

    assert resposta.status_code == 422
