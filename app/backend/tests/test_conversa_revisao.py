"""Regressões da revisão independente: respostas que confirmariam algo diferente do que foi mostrado."""
import pytest

from app.backend.assistant.dialogue import MAX_REJECTIONS, limitar
from app.backend.tests.helpers import NASCIMENTO_ADULTO, ClinicaApi


def _cardiologia(api: ClinicaApi, horarios: list[tuple[str, str]], nascimento: str | None = None):
    extra = (nascimento,) if nascimento else ()
    headers, paciente_id = api.cadastrar_paciente("Lurdes Andrade", "lurdes@email.com", "10006172547", *extra)
    medico = api.cadastrar_medico("Dr. João Mendes", "CRM-SP-1001", "Cardiologia")
    vagas = [api.cadastrar_horario(medico, data, hora) for data, hora in horarios]
    return api.conversa(headers), paciente_id, medico, vagas


TRES_VAGAS = [("2026-11-10", "09:00"), ("2026-11-12", "10:00"), ("2026-11-13", "10:00")]


def test_esclarecimento_feito_na_confirmacao_nao_confirma_o_horario_anterior(api: ClinicaApi) -> None:
    conversa, _, _, vagas = _cardiologia(api, TRES_VAGAS, NASCIMENTO_ADULTO)
    conversa.enviar("quero marcar cardiologia")
    conversa.enviar("3")

    duvida = conversa.enviar("segunda")
    resposta = conversa.enviar("sim")

    assert duvida["resultado"] == "esclarecer_opcao"
    assert [opcao["codigo"] for opcao in duvida["opcoes"]] == ["escolher", "buscar_dia"]
    assert duvida["contexto"]["acao_pendente"]["horario_id"] is None
    assert resposta["resultado"] != "consulta_agendada"
    assert api.consultas_no_banco() == []


def test_desmarcar_vale_so_para_o_horario_mostrado(api: ClinicaApi) -> None:
    conversa, paciente_id, medico, vagas = _cardiologia(api, TRES_VAGAS[:2])
    consulta = api.agendar_pela_recepcao(paciente_id, medico, vagas[0], "2026-11-10")
    pergunta = conversa.enviar("quero desmarcar minha consulta")
    # A recepção muda a consulta enquanto a pergunta está na tela.
    api.client.put(f"/api/consultas/{consulta}", headers=api.admin, json={"horario_id": vagas[1], "confirmado": True})

    resposta = conversa.tocar("desmarcar_consulta", em=pergunta)

    assert resposta["resultado"] == "confirmar_cancelamento"
    assert resposta["resposta"].startswith("Essa consulta mudou desde a pergunta anterior e nada foi alterado.")
    assert "quinta-feira, 12 de novembro, às 10 horas" in resposta["resposta"]
    assert api.consultas_no_banco() == [(consulta, vagas[1], "agendada")]
    assert conversa.tocar("desmarcar_consulta")["resultado"] == "consulta_cancelada"
    assert api.consultas_no_banco() == [(consulta, vagas[1], "cancelada")]


def test_pedido_de_cancelamento_da_clinica_vale_so_para_o_horario_mostrado(api: ClinicaApi) -> None:
    conversa, paciente_id, medico, vagas = _cardiologia(api, TRES_VAGAS[:2])
    consulta = api.agendar_pela_recepcao(paciente_id, medico, vagas[0], "2026-11-10")
    api.client.post(f"/api/consultas/{consulta}/solicitacoes", headers=api.admin, json={"tipo": "cancelamento"})
    pedido = conversa.enviar("oi")
    api.client.put(f"/api/consultas/{consulta}", headers=api.admin, json={"horario_id": vagas[1], "confirmado": True})

    resposta = conversa.tocar("desmarcar_consulta", em=pedido)

    assert resposta["resultado"] == "solicitacao_cancelamento"
    assert "Essa consulta mudou" in resposta["resposta"]
    assert api.consultas_no_banco() == [(consulta, vagas[1], "agendada")]


@pytest.mark.parametrize(
    ("frase", "esperado"),
    [("sim, pode remarcar", "remarcacao_aceita"), ("aceito remarcar", "remarcacao_aceita"),
     ("não sei se quero remarcar", "solicitacao_remarcacao"), ("o que é remarcar?", "solicitacao_remarcacao"),
     ("não quero trocar", "solicitacao_recusada")],
)
def test_frases_com_verbo_diante_do_pedido_de_troca_da_clinica(api: ClinicaApi, frase: str, esperado: str) -> None:
    conversa, paciente_id, medico, vagas = _cardiologia(api, TRES_VAGAS[:2])
    consulta = api.agendar_pela_recepcao(paciente_id, medico, vagas[0], "2026-11-10")
    corpo = {"tipo": "reagendamento", "horario_id": vagas[1]}
    api.client.post(f"/api/consultas/{consulta}/solicitacoes", headers=api.admin, json=corpo)
    conversa.enviar("oi")

    resposta = conversa.enviar(frase)

    assert resposta["resultado"] == esperado
    horario = vagas[1] if esperado == "remarcacao_aceita" else vagas[0]
    assert api.consultas_no_banco() == [(consulta, horario, "agendada")]


@pytest.mark.parametrize(
    ("frase", "esperado"),
    [("sim, pode cancelar", "consulta_cancelada"), ("não sei se quero cancelar", "confirmar_cancelamento"),
     ("o que acontece se eu cancelar?", "confirmar_cancelamento"), ("não precisa cancelar", "cancelamento_descartado")],
)
def test_frases_com_verbo_diante_da_confirmacao_de_cancelamento(api: ClinicaApi, frase: str, esperado: str) -> None:
    conversa, paciente_id, medico, vagas = _cardiologia(api, TRES_VAGAS[:2])
    primeira = api.agendar_pela_recepcao(paciente_id, medico, vagas[0], "2026-11-10")
    segunda = api.agendar_pela_recepcao(paciente_id, medico, vagas[1], "2026-11-12")
    pergunta = conversa.enviar("quero desmarcar a consulta do dia 10/11")
    assert pergunta["resultado"] == "confirmar_cancelamento"

    resposta = conversa.enviar(frase)

    assert resposta["resultado"] == esperado
    status = "cancelada" if esperado == "consulta_cancelada" else "agendada"
    assert api.consultas_no_banco() == [(primeira, vagas[0], status), (segunda, vagas[1], "agendada")]


@pytest.mark.parametrize(
    ("frase", "marcou"),
    [("pode marcar?", False), ("quero marcar esse horário", True), ("tanto faz", False), ("sim, pode marcar", True)],
)
def test_frases_diante_da_confirmacao_de_horario(api: ClinicaApi, frase: str, marcou: bool) -> None:
    conversa, _, _, vagas = _cardiologia(api, TRES_VAGAS[:2])
    conversa.enviar("quero marcar cardiologia")
    proposta = conversa.enviar("2")

    resposta = conversa.enviar(frase)

    if marcou:
        assert api.consultas_no_banco()[0][1:] == (vagas[1], "agendada")
    else:
        assert resposta["contexto"]["acao_pendente"] == proposta["contexto"]["acao_pendente"]
        assert api.consultas_no_banco() == []


def test_frases_com_verbo_diante_da_confirmacao_de_troca(api: ClinicaApi) -> None:
    conversa, paciente_id, medico, vagas = _cardiologia(api, TRES_VAGAS[:2])
    consulta = api.agendar_pela_recepcao(paciente_id, medico, vagas[0], "2026-11-10")
    conversa.enviar("quero remarcar minha consulta")
    proposta = conversa.enviar("dia 12/11 às 10h")

    duvida = conversa.enviar("como assim, vai mudar minha consulta?")
    troca = conversa.enviar("sim, pode remarcar")

    assert duvida["contexto"]["acao_pendente"] == proposta["contexto"]["acao_pendente"]
    assert troca["resultado"] == "remarcacao_aceita"
    assert api.consultas_no_banco() == [(consulta, vagas[1], "agendada")]


def test_vaga_perdida_mantem_o_aviso_de_fora_do_periodo(api: ClinicaApi) -> None:
    conversa, _, medico, vagas = _cardiologia(api, [("2026-11-12", "09:00"), ("2026-11-13", "09:00")])
    lista = conversa.enviar("quero marcar cardiologia dia 10/11")
    assert "fora do período pedido" in lista["resposta"]
    conversa.enviar("1")
    _, outro = api.cadastrar_paciente("Beto Souza", "beto@email.com", "12345678902")
    api.agendar_pela_recepcao(outro, medico, vagas[0], "2026-11-12")

    resposta = conversa.enviar("sim")

    assert "Essa opção não está mais disponível" in resposta["resposta"]
    assert "fora do período pedido" in resposta["resposta"]
    assert resposta["contexto"]["acao_pendente"]["horario_id"] == vagas[1]


def test_lista_de_recusados_fica_no_limite_do_contexto() -> None:
    assert len(limitar(range(500))) == MAX_REJECTIONS
    assert limitar(range(500))[-1] == 499
    mantida = limitar([7, *range(1000, 1300)], manter=7)
    assert len(mantida) == MAX_REJECTIONS and mantida[0] == 7 and mantida.count(7) == 1
