import pytest

from app.backend.tests.helpers import ClinicaApi


def _paciente_com_agenda(api: ClinicaApi) -> tuple[dict[str, str], list[int]]:
    headers, _ = api.cadastrar_paciente("Lurdes Andrade", "lurdes@email.com", "10006172547")
    medico = api.cadastrar_medico("Dr. João Mendes", "CRM-SP-1001", "Cardiologia")
    horarios = [
        api.cadastrar_horario(medico, data, hora)
        for data, hora in (("2026-11-10", "09:00"), ("2026-11-10", "10:00"), ("2026-11-12", "14:00"))
    ]
    return headers, horarios



def test_paciente_lista_vagas_sem_repetir_e_depois_desiste(api: ClinicaApi) -> None:
    headers, horarios = _paciente_com_agenda(api)
    conversa = api.conversa(headers)
    primeira = conversa.enviar("Quero agendar cardiologista na próxima semana")
    segunda = conversa.enviar("outro")
    desistencia = conversa.enviar("não")
    assert primeira["contexto"]["acao_pendente"]["horarios_oferecidos"] == horarios
    assert primeira["contexto"]["acao_pendente"]["horario_id"] is None
    assert segunda["resultado"] == "sem_horarios"
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
    conversa.enviar("sim")

    resposta = conversa.enviar("quais são minhas consultas?")

    assert resposta["resultado"] == "lista_consultas"
    assert "12/11/2026 às 14:00 — Dr. João Mendes (Cardiologia)" in resposta["resposta"]


def _paciente_com_clinico_e_ortopedista(api: ClinicaApi) -> tuple[dict[str, str], dict[str, int]]:
    headers, _ = api.cadastrar_paciente("Lurdes Andrade", "lurdes@email.com", "10006172547")
    medicos = {
        "Clínica Geral": api.cadastrar_medico("Dra. Maria Silva", "CRM-SP-2002", "Clínica Geral"),
        "Ortopedia": api.cadastrar_medico("Dr. Carlos Lima", "CRM-SP-3003", "Ortopedia"),
    }
    horarios = {
        especialidade: api.cadastrar_horario(medico, "2026-11-10", "09:00") for especialidade, medico in medicos.items()
    }
    return headers, horarios



def test_pedido_sem_especialidade_mostra_clinico_geral_sem_pergunta(api: ClinicaApi) -> None:
    headers, horarios = _paciente_com_clinico_e_ortopedista(api)
    resposta = api.conversa(headers).enviar("marcar consulta")
    assert resposta["resultado"] == "sugestao_horario"
    assert resposta["contexto"]["acao_pendente"]["criterios"]["especialidade"] == "Clínica Geral"
    assert resposta["contexto"]["acao_pendente"]["horario_id"] == horarios["Clínica Geral"]
    assert "Como você não indicou uma especialidade" in resposta["resposta"]
    assert api.horario_disponivel(horarios["Clínica Geral"])



def test_paciente_padrao_tambem_recebe_vagas_de_clinica_geral(api: ClinicaApi) -> None:
    headers, horarios = _paciente_com_clinico_e_ortopedista(api)
    resposta = api.conversa(headers).enviar("Quero agendar uma consulta para amanhã às 10h, por favor.")
    assert resposta["resultado"] == "sugestao_horario"
    assert resposta["contexto"]["acao_pendente"]["criterios"]["especialidade"] == "Clínica Geral"
    assert "alternativas" in resposta["resposta"]
    assert api.horario_disponivel(horarios["Clínica Geral"])


@pytest.mark.parametrize(
    ("mensagens", "especialidade"),
    [
        (["quero marcar uma consulta para ver minha dor nas costas"], "Ortopedia"),
        (["marcar consulta", "dor nas costas"], "Ortopedia"),
        (["quero marcar com qualquer médico"], "Clínica Geral"),
        (["marcar consulta", "não sei"], "Clínica Geral"),
        (["marcar consulta", "geral"], "Clínica Geral"),
        (["marcar consulta", "qualquer um"], "Clínica Geral"),
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


def test_pedido_de_remedio_do_paciente_padrao_e_bloqueado_e_vira_oferta_de_consulta(api: ClinicaApi) -> None:
    headers, horarios = _paciente_com_clinico_e_ortopedista(api)
    conversa = api.conversa(headers)

    recusa = conversa.enviar("Estou com dor de cabeça, qual remédio eu devo tomar?")

    assert recusa["perfil"] == "PADRAO"
    assert recusa["intencao"] == "orientacao_medica"
    assert recusa["resultado"] == "orientacao_medica_bloqueada"
    assert recusa["resposta"] == (
        "Como assistente virtual, não tenho permissão para realizar diagnósticos ou indicar medicamentos. "
        "Deseja agendar uma consulta com um Clínico Geral para avaliar seus sintomas?"
    )
    assert recusa["contexto"]["acao_pendente"]["criterios"]["especialidade"] == "Clínica Geral"
    assert all(api.horario_disponivel(horario) for horario in horarios.values())

    assert conversa.enviar("não")["resultado"] == "agendamento_descartado"


def test_pedido_de_remedio_do_paciente_idoso_e_recusado_com_linguagem_simples_e_leva_a_consulta(
    api: ClinicaApi,
) -> None:
    headers, horarios = _paciente_com_clinico_e_ortopedista(api)
    conversa = api.conversa(headers)

    recusa = conversa.enviar("to com dor de cabeca q nao passa, qual remedio eu tomo")
    sugestao = conversa.enviar("sim")
    confirmacao = conversa.enviar("sim")

    assert recusa["perfil"] == "IDOSO"
    assert recusa["resultado"] == "orientacao_medica_bloqueada"
    assert "Não posso indicar remédios nem dizer qual é a doença." in recusa["resposta"]
    assert sugestao["contexto"]["acao_pendente"]["horario_id"] == horarios["Clínica Geral"]
    assert confirmacao["resultado"] == "consulta_agendada"
    assert confirmacao["consulta"]["especialidade"] == "Clínica Geral"


def test_pedido_de_remedio_no_meio_de_um_agendamento_e_bloqueado_sem_marcar_nada(api: ClinicaApi) -> None:
    headers, horarios = _paciente_com_clinico_e_ortopedista(api)
    conversa = api.conversa(headers)
    conversa.enviar("quero marcar uma consulta para ver minha dor nas costas")

    resposta = conversa.enviar("qual remédio eu tomo até lá?")

    assert resposta["resultado"] == "orientacao_medica_bloqueada"
    assert api.horario_disponivel(horarios["Ortopedia"])


def test_usuario_sem_cadastro_de_paciente_e_orientado(api: ClinicaApi) -> None:
    usuario = api.cadastrar_usuario("Sem Cadastro", "sem@email.com")

    resposta = api.conversa(api.cabecalho_de(usuario["id"])).enviar("Quero marcar uma consulta")

    assert resposta["resultado"] == "paciente_nao_cadastrado"


def test_senha_acima_do_limite_do_bcrypt_e_rejeitada(api: ClinicaApi) -> None:
    resposta = api.client.post(
        "/api/auth/register", headers=api.admin, json={"nome": "Ana", "email": "ana@email.com", "senha": "ç" * 37}
    )

    assert resposta.status_code == 422
