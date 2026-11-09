from app.backend.tests.helpers import SENHA_PADRAO, ClinicaApi


def _cenario(api: ClinicaApi) -> dict:
    paciente_headers, paciente = api.cadastrar_paciente("Lurdes Andrade", "lurdes@email.com", "12345678901")
    medico = api.cadastrar_medico("Dr. João Mendes", "CRM-SP-1", "Cardiologia")
    atual = api.cadastrar_horario(medico, "2026-11-10", "09:00")
    novo = api.cadastrar_horario(medico, "2026-11-12", "10:00")
    consulta = api.client.post(
        "/api/consultas",
        headers=api.admin,
        json={"paciente_id": paciente, "medico_id": medico, "horario_id": atual, "data": "2026-11-10"},
    ).json()["id"]
    return {"paciente": paciente_headers, "medico": medico, "atual": atual, "novo": novo, "consulta": consulta}


def _solicitar(api: ClinicaApi, cenario: dict, **pedido: object):
    return api.client.post(f"/api/consultas/{cenario['consulta']}/solicitacoes", headers=api.admin, json=pedido)


def _notificacoes(api: ClinicaApi, headers: dict[str, str]) -> list[dict]:
    return api.client.get("/api/notificacoes", headers=headers).json()


def _responder(api: ClinicaApi, headers: dict[str, str], notificacao_id: int, aceitar: bool):
    return api.client.post(f"/api/notificacoes/{notificacao_id}/responder", headers=headers, json={"aceitar": aceitar})


def test_remarcacao_pedida_pela_recepcao_so_acontece_quando_o_paciente_aceita(api: ClinicaApi) -> None:
    cenario = _cenario(api)

    pedido = _solicitar(api, cenario, tipo="reagendamento", horario_id=cenario["novo"], motivo="Médico em congresso")

    assert pedido.status_code == 201
    assert not api.horario_disponivel(cenario["atual"]) and api.horario_disponivel(cenario["novo"])
    [notificacao] = _notificacoes(api, cenario["paciente"])
    assert notificacao["acao_necessaria"] and notificacao["tipo"] == "reagendamento_pendente"
    assert "12/11/2026 às 10:00" in notificacao["mensagem"] and "Médico em congresso" in notificacao["mensagem"]

    resposta = _responder(api, cenario["paciente"], notificacao["id"], aceitar=True)

    assert resposta.json()["status"] == "aceito"
    assert api.horario_disponivel(cenario["atual"]) and not api.horario_disponivel(cenario["novo"])
    assert _notificacoes(api, cenario["paciente"]) == []
    [aviso] = _notificacoes(api, api.admin)
    assert not aviso["acao_necessaria"] and "Lurdes Andrade aceitou a remarcação da consulta" in aviso["mensagem"]


def test_paciente_recusa_e_a_consulta_continua_igual(api: ClinicaApi) -> None:
    cenario = _cenario(api)
    notificacao = _solicitar(api, cenario, tipo="reagendamento", horario_id=cenario["novo"]).json()

    _responder(api, cenario["paciente"], notificacao["id"], aceitar=False)

    assert not api.horario_disponivel(cenario["atual"]) and api.horario_disponivel(cenario["novo"])
    assert "recusou a remarcação" in _notificacoes(api, api.admin)[0]["mensagem"]


def test_cancelamento_aceito_libera_o_horario(api: ClinicaApi) -> None:
    cenario = _cenario(api)
    notificacao = _solicitar(api, cenario, tipo="cancelamento").json()

    _responder(api, cenario["paciente"], notificacao["id"], aceitar=True)

    assert api.horario_disponivel(cenario["atual"])
    detalhe = api.client.get(f"/api/consultas/{cenario['consulta']}", headers=api.admin).json()
    assert detalhe["status"] == "cancelada"


def test_agenda_mostra_o_pedido_pendente_e_impede_um_segundo(api: ClinicaApi) -> None:
    cenario = _cenario(api)
    _solicitar(api, cenario, tipo="cancelamento")

    segundo = _solicitar(api, cenario, tipo="reagendamento", horario_id=cenario["novo"])

    assert segundo.status_code == 409
    detalhe = api.client.get(f"/api/consultas/{cenario['consulta']}", headers=api.admin).json()
    assert detalhe["solicitacao_pendente"] == "cancelamento_pendente"


def test_horario_tomado_antes_do_aceite_mantem_o_pedido_pendente(api: ClinicaApi) -> None:
    cenario = _cenario(api)
    notificacao = _solicitar(api, cenario, tipo="reagendamento", horario_id=cenario["novo"]).json()
    _, outro = api.cadastrar_paciente("Beto Souza", "beto@email.com", "12345678902")
    api.client.post(
        "/api/consultas",
        headers=api.admin,
        json={
            "paciente_id": outro, "medico_id": cenario["medico"], "horario_id": cenario["novo"], "data": "2026-11-12"
        },
    )

    resposta = _responder(api, cenario["paciente"], notificacao["id"], aceitar=True)

    assert resposta.status_code == 409
    assert [n["id"] for n in _notificacoes(api, cenario["paciente"])] == [notificacao["id"]]
    assert not api.horario_disponivel(cenario["atual"])


def test_somente_o_destinatario_responde_e_somente_a_equipe_pede(api: ClinicaApi) -> None:
    cenario = _cenario(api)
    notificacao = _solicitar(api, cenario, tipo="cancelamento").json()

    assert _responder(api, api.admin, notificacao["id"], aceitar=True).status_code == 404
    pedido_do_paciente = api.client.post(
        f"/api/consultas/{cenario['consulta']}/solicitacoes", headers=cenario["paciente"], json={"tipo": "cancelamento"}
    )
    assert pedido_do_paciente.status_code == 403
    _responder(api, cenario["paciente"], notificacao["id"], aceitar=False)
    assert _responder(api, cenario["paciente"], notificacao["id"], aceitar=True).status_code == 409


def test_cancelamento_pelo_chat_avisa_o_medico_e_a_recepcao(api: ClinicaApi) -> None:
    ficha = {"crm": "CRM-SP-77", "especialidade": "Neurologia"}
    api.client.post(
        "/api/auth/register",
        headers=api.medico,
        json={
            "nome": "Dr. Rafael", "email": "rafael@email.com", "senha": SENHA_PADRAO, "papel": "medico", "medico": ficha
        },
    )
    rafael_login = api.client.post("/api/auth/login", json={"email": "rafael@email.com", "senha": SENHA_PADRAO}).json()
    rafael = {"Authorization": f"Bearer {rafael_login['token']}"}
    medico_id = api.client.get("/api/auth/me", headers=rafael).json()["medico_id"]
    paciente_headers, paciente = api.cadastrar_paciente("Lurdes Andrade", "lurdes@email.com", "12345678901")
    horario = api.cadastrar_horario(medico_id, "2026-11-10", "09:00")
    api.client.post(
        "/api/consultas",
        headers=api.admin,
        json={"paciente_id": paciente, "medico_id": medico_id, "horario_id": horario, "data": "2026-11-10"},
    )
    conversa = api.conversa(paciente_headers)

    conversa.enviar("Cancelar minha consulta do dia 10/11")
    assert conversa.enviar("sim")["resultado"] == "consulta_cancelada"

    for headers in (rafael, api.admin):
        [aviso] = _notificacoes(api, headers)
        esperado = "Lurdes Andrade cancelou pelo assistente a consulta com Dr. Rafael de 10/11/2026 às 09:00"
        assert esperado in aviso["mensagem"]


def test_assistente_apresenta_o_pedido_uma_vez_e_aceita_com_sim(api: ClinicaApi) -> None:
    cenario = _cenario(api)
    _solicitar(api, cenario, tipo="reagendamento", horario_id=cenario["novo"])
    conversa = api.conversa(cenario["paciente"])

    pedido = conversa.enviar("oi")
    assert pedido["resultado"] == "solicitacao_remarcacao"
    assert "Recepção pediu para mudar sua consulta." in pedido["resposta"]
    assert "quinta-feira, 12 de novembro" in pedido["resposta"]

    aceite = conversa.enviar("sim")
    assert aceite["resultado"] == "remarcacao_aceita"
    assert not api.horario_disponivel(cenario["novo"])
    assert conversa.enviar("oi")["resultado"] == "saudacao"


def test_pedido_ignorado_no_chat_nao_volta_a_interromper(api: ClinicaApi) -> None:
    cenario = _cenario(api)
    _solicitar(api, cenario, tipo="cancelamento")
    conversa = api.conversa(cenario["paciente"])

    assert conversa.enviar("oi")["resultado"] == "solicitacao_cancelamento"
    assert conversa.enviar("quais são minhas consultas?")["resultado"] == "lista_consultas"
    assert conversa.enviar("oi")["resultado"] == "saudacao"
    assert len(_notificacoes(api, cenario["paciente"])) == 1


def test_alteracao_aplicada_direto_pela_equipe_avisa_o_paciente(api: ClinicaApi) -> None:
    cenario = _cenario(api)

    api.client.put(
        f"/api/consultas/{cenario['consulta']}",
        headers=api.admin,
        json={"horario_id": cenario["novo"], "confirmado": True},
    )

    [aviso] = _notificacoes(api, cenario["paciente"])
    assert "Recepção remarcou, com a sua confirmação, a consulta" in aviso["mensagem"]
