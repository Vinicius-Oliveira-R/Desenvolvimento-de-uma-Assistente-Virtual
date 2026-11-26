"""Retomada pela rota /assistant/retomar e abertura com as três opções do paciente."""
from app.backend.tests.helpers import ClinicaApi


def _agenda(api: ClinicaApi):
    headers, paciente_id = api.cadastrar_paciente("Lurdes Andrade", "lurdes@email.com", "10006172547")
    medico = api.cadastrar_medico("Dr. João Mendes", "CRM-SP-1001", "Cardiologia")
    vagas = [api.cadastrar_horario(medico, "2026-11-10", "09:00"), api.cadastrar_horario(medico, "2026-11-10", "14:00")]
    return api.conversa(headers), paciente_id, medico, vagas


def test_retomar_exige_identidade(api: ClinicaApi) -> None:
    assert api.client.post("/api/assistant/retomar", json={"contexto": {}}).status_code == 401


def test_abertura_sem_conversa_oferece_as_tres_operacoes(api: ClinicaApi) -> None:
    conversa, _, _, _ = _agenda(api)

    abertura = conversa.retomar()

    assert abertura["resultado"] == "saudacao"
    assert [(opcao["codigo"], opcao["rotulo"], opcao["proposta"]) for opcao in abertura["opcoes"]] == [
        ("marcar_consulta", "Marcar consulta", None),
        ("minhas_consultas", "Minhas consultas", None),
        ("mudar_ou_cancelar", "Mudar ou cancelar", None),
    ]


def test_retomada_reapresenta_a_confirmacao_pendente_sem_alterar_nada(api: ClinicaApi) -> None:
    conversa, _, _, vagas = _agenda(api)
    conversa.enviar("quero marcar cardiologia")
    escolha = conversa.tocar("escolher", "1")

    retomada = conversa.retomar()

    assert retomada["resposta"].startswith("Continuando de onde paramos.")
    assert "terça-feira, 10 de novembro, às 9 horas" in retomada["resposta"]
    assert retomada["contexto"]["acao_pendente"] == escolha["contexto"]["acao_pendente"]
    assert [opcao["codigo"] for opcao in retomada["opcoes"]] == ["confirmar_horario", "outro_horario"]
    assert api.consultas_no_banco() == []
    assert conversa.tocar("confirmar_horario")["resultado"] == "consulta_agendada"
    assert [horario for _, horario, _ in api.consultas_no_banco()] == [vagas[0]]


def test_retomada_revalida_a_vaga_escolhida(api: ClinicaApi) -> None:
    conversa, _, medico, vagas = _agenda(api)
    conversa.enviar("quero marcar cardiologia")
    escolha = conversa.tocar("escolher", "1")
    _, outro = api.cadastrar_paciente("Beto Souza", "beto@email.com", "12345678902")
    api.agendar_pela_recepcao(outro, medico, vagas[0], "2026-11-10")

    retomada = conversa.retomar()

    assert "Essa opção não está mais disponível" in retomada["resposta"]
    assert retomada["contexto"]["acao_pendente"]["horario_id"] == vagas[1]
    assert retomada["contexto"]["acao_pendente"]["proposta"] != escolha["contexto"]["acao_pendente"]["proposta"]
    assert conversa.tocar("confirmar_horario", em=escolha)["resposta"].startswith("Esse botão era de uma pergunta anterior")
    assert len(api.consultas_no_banco()) == 1


def test_novo_agendamento_encerra_a_proposta_e_preserva_as_consultas(api: ClinicaApi) -> None:
    conversa, paciente_id, medico, vagas = _agenda(api)
    terceira = api.cadastrar_horario(medico, "2026-11-12", "10:00")
    existente = api.agendar_pela_recepcao(paciente_id, medico, terceira, "2026-11-12")
    clinico = api.cadastrar_medico("Dra. Maria Silva", "CRM-SP-2002", "Clínica Geral")
    api.cadastrar_horario(clinico, "2026-11-11", "08:00")
    conversa.enviar("quero marcar cardiologia")
    antiga = conversa.tocar("escolher", "1")

    # "Novo agendamento" no front-end descarta a ação pendente e pede outra busca.
    conversa.contexto = {**conversa.contexto, "acao_pendente": None}
    nova = conversa.tocar("marcar_consulta", em=conversa.retomar())
    resposta = conversa.tocar("confirmar_horario", em=antiga)

    assert nova["resultado"] == "sugestao_horario"
    assert "pergunta anterior" in resposta["resposta"]
    assert api.consultas_no_banco() == [(existente, terceira, "agendada")]


def test_retomada_apresenta_pedido_da_clinica_ainda_nao_visto(api: ClinicaApi) -> None:
    conversa, paciente_id, medico, vagas = _agenda(api)
    consulta = api.agendar_pela_recepcao(paciente_id, medico, vagas[0], "2026-11-10")
    api.client.post(f"/api/consultas/{consulta}/solicitacoes", headers=api.admin, json={"tipo": "cancelamento"})

    pedido = conversa.retomar()
    reaberto = conversa.retomar()

    assert pedido["resultado"] == reaberto["resultado"] == "solicitacao_cancelamento"
    assert [opcao["rotulo"] for opcao in pedido["opcoes"]] == ["Desmarcar consulta", "Manter minha consulta"]
    assert reaberto["contexto"]["acao_pendente"]["proposta"] == pedido["contexto"]["acao_pendente"]["proposta"]
    assert api.consultas_no_banco() == [(consulta, vagas[0], "agendada")]


def test_mudar_ou_cancelar_pela_abertura_identifica_a_consulta_e_confirma(api: ClinicaApi) -> None:
    conversa, paciente_id, medico, vagas = _agenda(api)
    consulta = api.agendar_pela_recepcao(paciente_id, medico, vagas[0], "2026-11-10")

    escolha = conversa.tocar("mudar_ou_cancelar", em=conversa.retomar())
    pergunta = conversa.tocar("desmarcar_esta")
    desmarcada = conversa.tocar("desmarcar_consulta")

    assert escolha["resultado"] == "escolher_acao"
    assert [opcao["rotulo"] for opcao in escolha["opcoes"]] == ["Mudar o horário", "Desmarcar esta consulta"]
    assert pergunta["resultado"] == "confirmar_cancelamento"
    assert desmarcada["resultado"] == "consulta_cancelada"
    assert api.consultas_no_banco() == [(consulta, vagas[0], "cancelada")]


def test_minhas_consultas_pela_abertura(api: ClinicaApi) -> None:
    conversa, paciente_id, medico, vagas = _agenda(api)
    api.agendar_pela_recepcao(paciente_id, medico, vagas[1], "2026-11-10")

    lista = conversa.tocar("minhas_consultas", em=conversa.retomar())

    assert lista["resultado"] == "lista_consultas"
    assert "terça-feira, 10 de novembro, às 14 horas" in lista["resposta"]
