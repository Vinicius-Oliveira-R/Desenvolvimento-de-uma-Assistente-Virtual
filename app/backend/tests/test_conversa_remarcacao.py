"""Remarcação: mostra o horário atual e o proposto e preserva a consulta original se a troca falhar."""
from app.backend.assistant import scheduling_flow
from app.backend.tests.helpers import ClinicaApi

NASCIMENTO_72_ANOS = "1954-05-20"


def _consulta_marcada(api: ClinicaApi, nascimento: str = NASCIMENTO_72_ANOS):
    headers, paciente_id = api.cadastrar_paciente("Lurdes Andrade", "lurdes@email.com", "10006172547", nascimento)
    medico = api.cadastrar_medico("Dr. João Mendes", "CRM-SP-1001", "Cardiologia")
    sexta = api.cadastrar_horario(medico, "2026-11-06", "09:00")
    consulta = api.agendar_pela_recepcao(paciente_id, medico, sexta, "2026-11-06")
    return api.conversa(headers), medico, sexta, consulta


def _ocupar(api: ClinicaApi, medico: int, horario: int, data: str) -> None:
    _, outro = api.cadastrar_paciente("Beto Souza", "beto@email.com", "12345678902")
    api.agendar_pela_recepcao(outro, medico, horario, data)


def test_idoso_com_pedido_direto_tem_os_detalhes_aproveitados_de_imediato(api: ClinicaApi) -> None:
    conversa, medico, sexta, consulta = _consulta_marcada(api)
    api.cadastrar_horario(medico, "2026-11-09", "08:00")
    segunda_tarde = api.cadastrar_horario(medico, "2026-11-09", "15:00")

    proposta = conversa.enviar("quero mudar minha consulta de sexta para segunda à tarde")

    assert proposta["estilo"] == "passo_a_passo"
    assert proposta["intencao"] == "remarcar"
    pendente = proposta["contexto"]["acao_pendente"]
    assert (pendente["tipo"], pendente["consulta_id"], pendente["horario_id"]) == ("remarcar", consulta, segunda_tarde)
    assert "Sua consulta agora: sexta-feira, 6 de novembro, às 9 horas" in proposta["resposta"]
    assert "Novo horário: segunda-feira, 9 de novembro, às 15 horas" in proposta["resposta"]
    assert [opcao["rotulo"] for opcao in proposta["opcoes"]] == ["Confirmar troca", "Manter minha consulta"]
    assert api.consultas_no_banco() == [(consulta, sexta, "agendada")]

    troca = conversa.tocar("confirmar_troca")

    assert troca["resultado"] == "remarcacao_aceita"
    assert "O horário antigo, sexta-feira, 6 de novembro, às 9 horas, ficou livre." in troca["resposta"]
    assert api.consultas_no_banco() == [(consulta, segunda_tarde, "agendada")]
    assert api.horario_disponivel(sexta)


def test_vaga_de_destino_perdida_antes_da_confirmacao_mantem_a_consulta_original(api: ClinicaApi) -> None:
    conversa, medico, sexta, consulta = _consulta_marcada(api)
    destino = api.cadastrar_horario(medico, "2026-11-11", "10:00")
    conversa.enviar("quero remarcar minha consulta")
    proposta = conversa.enviar("dia 11/11 às 10h")
    assert proposta["contexto"]["acao_pendente"]["horario_id"] == destino
    _ocupar(api, medico, destino, "2026-11-11")

    resposta = conversa.tocar("confirmar_troca")

    assert resposta["resultado"] in ("sugestao_horario", "sem_horarios")
    assert "não está mais disponível" in resposta["resposta"]
    assert "Sua consulta atual continua marcada." in resposta["resposta"]
    assert (consulta, sexta, "agendada") in api.consultas_no_banco()
    assert not api.horario_disponivel(sexta)


def test_vaga_ocupada_durante_a_transferencia_desfaz_tudo(api: ClinicaApi, monkeypatch) -> None:
    conversa, medico, sexta, consulta = _consulta_marcada(api)
    destino = api.cadastrar_horario(medico, "2026-11-11", "10:00")
    conversa.enviar("quero remarcar minha consulta")
    conversa.enviar("dia 11/11 às 10h")
    _ocupar(api, medico, destino, "2026-11-11")
    # Simula a corrida: a vaga parece livre na conferência e é tomada antes do bloqueio da transação.
    monkeypatch.setattr(scheduling_flow.SchedulingDialogueManager, "_valid_option", lambda *_: object())

    resposta = conversa.tocar("confirmar_troca")

    assert "não está mais disponível" in resposta["resposta"]
    assert (consulta, sexta, "agendada") in api.consultas_no_banco()
    assert not api.horario_disponivel(sexta)


def test_clique_duplo_na_troca_nao_move_duas_vezes(api: ClinicaApi) -> None:
    conversa, medico, sexta, consulta = _consulta_marcada(api)
    destino = api.cadastrar_horario(medico, "2026-11-11", "10:00")
    conversa.enviar("quero remarcar minha consulta")
    proposta = conversa.enviar("dia 11/11 às 10h")

    conversa.tocar("confirmar_troca")
    conversa.contexto = proposta["contexto"]
    repetida = conversa.tocar("confirmar_troca", em=proposta)

    assert repetida["resultado"] == "remarcacao_aceita"
    assert "já estava feita" in repetida["resposta"]
    assert api.consultas_no_banco() == [(consulta, destino, "agendada")]


def test_ajuda_e_manter_na_troca_nao_mudam_a_consulta(api: ClinicaApi) -> None:
    conversa, medico, sexta, consulta = _consulta_marcada(api)
    api.cadastrar_horario(medico, "2026-11-11", "10:00")
    conversa.enviar("quero remarcar minha consulta")
    conversa.enviar("dia 11/11 às 10h")

    ajuda = conversa.enviar("como assim?")
    mantida = conversa.tocar("manter_consulta")

    assert ajuda["resposta"].startswith("Calma, vou repetir. Sua consulta ainda não mudou:")
    assert mantida["resultado"] == "cancelamento_descartado"
    assert "sexta-feira, 6 de novembro, às 9 horas" in mantida["resposta"]
    assert api.consultas_no_banco() == [(consulta, sexta, "agendada")]
