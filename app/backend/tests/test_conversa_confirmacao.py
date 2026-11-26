"""Confirmações: só o "sim" (ou o botão nomeado) da última pergunta altera a agenda.

Os cenários passam por /api/assistant/chat com o contexto devolvido pela API, como o
front-end faz, e conferem o estado das consultas no banco descartável do conftest.
"""
import pytest

from app.backend.tests.helpers import ClinicaApi

DUVIDAS = ("pode repetir?", "Pode repetir", "quero entender", "como assim?", "já está marcado?", "não sei", "não entendi", "?")


def _agenda(api: ClinicaApi):
    headers, paciente_id = api.cadastrar_paciente("Lurdes Andrade", "lurdes@email.com", "10006172547")
    medico = api.cadastrar_medico("Dr. João Mendes", "CRM-SP-1001", "Cardiologia")
    vagas = [api.cadastrar_horario(medico, "2026-11-10", "09:00"), api.cadastrar_horario(medico, "2026-11-10", "14:00")]
    return api.conversa(headers), paciente_id, medico, vagas


@pytest.mark.parametrize("duvida", DUVIDAS)
def test_duvida_depois_de_escolher_nao_marca_e_o_sim_marca_uma_unica_reserva(api: ClinicaApi, duvida: str) -> None:
    conversa, _, _, vagas = _agenda(api)
    conversa.enviar("quero marcar cardiologia")
    escolha = conversa.enviar("1")
    assert escolha["contexto"]["acao_pendente"]["horario_id"] == vagas[0]

    repeticao = conversa.enviar(duvida)

    assert repeticao["resultado"] == "sugestao_horario"
    assert "Sua consulta está marcada" not in repeticao["resposta"]
    assert repeticao["contexto"]["acao_pendente"] == escolha["contexto"]["acao_pendente"]
    assert api.consultas_no_banco() == []
    assert api.horario_disponivel(vagas[0])

    confirmacao = conversa.enviar("sim")

    assert confirmacao["resultado"] == "consulta_agendada"
    assert confirmacao["resposta"].startswith("Pronto! Sua consulta está marcada.")
    assert [(horario, status) for _, horario, status in api.consultas_no_banco()] == [(vagas[0], "agendada")]


def test_pergunta_sobre_a_situacao_responde_que_ainda_nao_esta_marcado(api: ClinicaApi) -> None:
    conversa, _, _, _ = _agenda(api)
    conversa.enviar("quero marcar cardiologia")
    conversa.enviar("2")

    resposta = conversa.enviar("já está marcado?")

    assert resposta["resposta"].startswith("Ainda não. A consulta só fica marcada depois que você confirmar")
    assert api.consultas_no_banco() == []


@pytest.mark.parametrize(
    "frase", ["pode desmarcar", "pode ser amanhã?", "quero saber o preço", "pode me ligar", "sim?", "quero ver"]
)
def test_frases_que_so_comecam_com_pode_ou_quero_nao_autorizam(api: ClinicaApi, frase: str) -> None:
    conversa, _, _, _ = _agenda(api)
    conversa.enviar("quero marcar cardiologia")
    conversa.enviar("1")

    resposta = conversa.enviar(frase)

    assert resposta["resultado"] != "consulta_agendada"
    assert api.consultas_no_banco() == []


@pytest.mark.parametrize("confirmacao", ["sim", "Sim, por favor!", "pode marcar", "confirmo", "pode ser", "isso mesmo"])
def test_confirmacoes_claras_por_texto_marcam(api: ClinicaApi, confirmacao: str) -> None:
    conversa, _, _, vagas = _agenda(api)
    conversa.enviar("quero marcar cardiologia")
    conversa.enviar("2")

    assert conversa.enviar(confirmacao)["resultado"] == "consulta_agendada"
    assert [horario for _, horario, _ in api.consultas_no_banco()] == [vagas[1]]


def test_confirmacao_por_botao_nomeado_e_clique_duplo_criam_uma_reserva(api: ClinicaApi) -> None:
    conversa, _, _, vagas = _agenda(api)
    conversa.enviar("quero marcar cardiologia")
    proposta = conversa.tocar("escolher", "2")
    assert [opcao["rotulo"] for opcao in proposta["opcoes"]] == ["Confirmar horário", "Ver outro horário"]

    primeira = conversa.tocar("confirmar_horario")
    # O segundo clique sai do navegador com a mesma sessão, antes de a resposta do primeiro chegar.
    conversa.contexto = proposta["contexto"]
    segunda = conversa.tocar("confirmar_horario", em=proposta)

    assert primeira["resultado"] == segunda["resultado"] == "consulta_agendada"
    assert "já estava marcada" in segunda["resposta"]
    assert [(horario, status) for _, horario, status in api.consultas_no_banco()] == [(vagas[1], "agendada")]


def test_botao_de_confirmacao_depois_de_concluir_e_ignorado(api: ClinicaApi) -> None:
    conversa, _, _, _ = _agenda(api)
    conversa.enviar("quero marcar cardiologia")
    proposta = conversa.tocar("escolher", "1")
    conversa.tocar("confirmar_horario")

    repetido = conversa.tocar("confirmar_horario", em=proposta)

    assert "pergunta anterior" in repetido["resposta"]
    assert len(api.consultas_no_banco()) == 1


def test_botao_de_uma_proposta_antiga_nao_confirma_a_mais_recente(api: ClinicaApi) -> None:
    conversa, _, _, vagas = _agenda(api)
    conversa.enviar("quero marcar cardiologia")
    antiga = conversa.tocar("escolher", "1")
    conversa.enviar("quero marcar cardiologia")
    recente = conversa.tocar("escolher", "2")

    resposta = conversa.tocar("confirmar_horario", em=antiga)

    assert "pergunta anterior" in resposta["resposta"]
    assert resposta["contexto"]["acao_pendente"] == recente["contexto"]["acao_pendente"]
    assert resposta["contexto"]["acao_pendente"]["horario_id"] == vagas[1]
    assert api.consultas_no_banco() == []


@pytest.mark.parametrize(
    "acao",
    [
        {"codigo": "desmarcar_consulta"},
        {"codigo": "confirmar_troca"},
        {"codigo": "escolher", "valor": "7"},
        {"codigo": "confirmar_horario", "proposta": "proposta-inventada"},
    ],
)
def test_botao_que_nao_corresponde_a_pergunta_atual_e_recusado(api: ClinicaApi, acao: dict) -> None:
    conversa, _, _, _ = _agenda(api)
    conversa.enviar("quero marcar cardiologia")
    proposta = conversa.enviar("1")["contexto"]["acao_pendente"]["proposta"]

    resposta = conversa.enviar("Confirmar", {"proposta": proposta, **acao})

    assert "pergunta anterior" in resposta["resposta"]
    assert api.consultas_no_banco() == []


def test_ajuda_durante_o_cancelamento_mantem_a_consulta(api: ClinicaApi) -> None:
    conversa, paciente_id, medico, vagas = _agenda(api)
    consulta = api.agendar_pela_recepcao(paciente_id, medico, vagas[0], "2026-11-10")
    pedido = conversa.enviar("quero desmarcar minha consulta")
    assert pedido["resultado"] == "confirmar_cancelamento"

    for duvida in DUVIDAS:
        resposta = conversa.enviar(duvida)
        assert resposta["resultado"] == "confirmar_cancelamento", duvida
        assert resposta["contexto"]["acao_pendente"] == pedido["contexto"]["acao_pendente"]
        assert api.consultas_no_banco() == [(consulta, vagas[0], "agendada")]

    assert [opcao["rotulo"] for opcao in resposta["opcoes"]] == ["Desmarcar consulta", "Manter minha consulta"]
    mantida = conversa.tocar("manter_consulta")
    assert mantida["resultado"] == "cancelamento_descartado"
    assert api.consultas_no_banco() == [(consulta, vagas[0], "agendada")]


def test_desmarcar_pelo_botao_identifica_e_registra(api: ClinicaApi) -> None:
    conversa, paciente_id, medico, vagas = _agenda(api)
    consulta = api.agendar_pela_recepcao(paciente_id, medico, vagas[0], "2026-11-10")
    pedido = conversa.enviar("quero desmarcar minha consulta")
    assert "terça-feira, 10 de novembro, às 9 horas, com Dr. João Mendes" in pedido["resposta"]

    feito = conversa.tocar("desmarcar_consulta")

    assert feito["resultado"] == "consulta_cancelada"
    assert "Era terça-feira, 10 de novembro, às 9 horas, com Dr. João Mendes." in feito["resposta"]
    assert api.consultas_no_banco() == [(consulta, vagas[0], "cancelada")]
    assert api.horario_disponivel(vagas[0])


@pytest.mark.parametrize("tipo", ["reagendamento", "cancelamento"])
def test_ajuda_durante_pedido_da_clinica_mantem_a_consulta(api: ClinicaApi, tipo: str) -> None:
    conversa, paciente_id, medico, vagas = _agenda(api)
    consulta = api.agendar_pela_recepcao(paciente_id, medico, vagas[0], "2026-11-10")
    corpo = {"tipo": tipo, **({"horario_id": vagas[1]} if tipo == "reagendamento" else {})}
    assert api.client.post(f"/api/consultas/{consulta}/solicitacoes", headers=api.admin, json=corpo).status_code == 201
    esperado = "solicitacao_remarcacao" if tipo == "reagendamento" else "solicitacao_cancelamento"
    assert conversa.enviar("oi")["resultado"] == esperado

    for duvida in (*DUVIDAS, "pode me explicar?", "quero pensar"):
        resposta = conversa.enviar(duvida)
        assert resposta["resultado"] == esperado, duvida
        assert api.consultas_no_banco() == [(consulta, vagas[0], "agendada")]

    errado = "desmarcar_consulta" if tipo == "reagendamento" else "confirmar_troca"
    proposta = resposta["contexto"]["acao_pendente"]["proposta"]
    assert "pergunta anterior" in conversa.enviar("Botão trocado", {"codigo": errado, "proposta": proposta})["resposta"]
    assert api.consultas_no_banco() == [(consulta, vagas[0], "agendada")]
    pendentes = api.client.get("/api/notificacoes", headers=conversa._headers).json()
    assert [n["acao_necessaria"] for n in pendentes] == [True]


def test_pedido_de_troca_da_clinica_aceito_pelo_botao_informa_antes_e_depois(api: ClinicaApi) -> None:
    conversa, paciente_id, medico, vagas = _agenda(api)
    consulta = api.agendar_pela_recepcao(paciente_id, medico, vagas[0], "2026-11-10")
    corpo = {"tipo": "reagendamento", "horario_id": vagas[1]}
    api.client.post(f"/api/consultas/{consulta}/solicitacoes", headers=api.admin, json=corpo)
    pedido = conversa.enviar("oi")
    assert [opcao["rotulo"] for opcao in pedido["opcoes"]] == ["Confirmar troca", "Manter minha consulta"]

    aceite = conversa.tocar("confirmar_troca")

    assert aceite["resultado"] == "remarcacao_aceita"
    assert "Agora é terça-feira, 10 de novembro, às 14 horas" in aceite["resposta"]
    assert "às 9 horas, ficou livre" in aceite["resposta"]
    assert api.consultas_no_banco() == [(consulta, vagas[1], "agendada")]
