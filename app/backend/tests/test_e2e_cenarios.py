"""Cenários E2E do assistente: o mesmo fluxo HTTP que o front-end Django executa via httpx.

Os testes de concorrência em nível de banco (threads, SQL emitido e PostgreSQL real) estão em test_concorrencia.py.
"""

import re

from app.backend.tests.helpers import ClinicaApi

MENSAGEM_RESERVADO = "Este horário acabou de ser reservado por outro paciente."


def _frases(texto: str) -> list[str]:
    return [frase for frase in re.split(r"[.!?:\n]+", texto) if frase.strip()]


def test_cenario_a_paciente_idoso_recebe_linguagem_simplificada(api: ClinicaApi) -> None:
    headers, _ = api.cadastrar_paciente("Lurdes Andrade", "lurdes@email.com", "55555555555")
    cardiologista = api.cadastrar_medico("Dr. João Mendes", "CRM-SP-1001", "Cardiologia")
    dermatologista = api.cadastrar_medico("Dra. Ana Costa", "CRM-SP-1002", "Dermatologia")
    api.cadastrar_horario(cardiologista, "2026-11-05", "09:00")
    api.cadastrar_horario(dermatologista, "2026-11-09", "08:00")
    proxima_semana = api.cadastrar_horario(cardiologista, "2026-11-10", "09:00")
    conversa = api.conversa(headers)

    sugestao = conversa.enviar("queria marca consulta com cardiologista pra semana q vem se der...")

    assert sugestao["perfil"] == "IDOSO"
    assert sugestao["intencao"] == "agendar"
    assert sugestao["entidades"]["especialidade"] == "Cardiologia"
    assert sugestao["heuristicas"]["taxa_erros"] > 0
    assert sugestao["heuristicas"]["hesitacao"] > 0
    assert sugestao["heuristicas"]["vagueza"] == 1.0
    assert sugestao["resultado"] == "sugestao_horario"
    assert sugestao["contexto"]["acao_pendente"]["horario_id"] == proxima_semana

    resposta = sugestao["resposta"]
    assert "médico do coração" in resposta
    assert "cardiolog" not in resposta.lower()
    assert "terça-feira, 10 de novembro" in resposta
    assert "1. Para marcar, escreva SIM." in resposta
    assert all(len(frase.split()) <= 12 for frase in _frases(resposta))

    confirmacao = conversa.enviar("sim")

    assert confirmacao["perfil"] == "IDOSO"
    assert confirmacao["resultado"] == "consulta_agendada"
    assert confirmacao["consulta"]["data"] == "2026-11-10"
    assert confirmacao["resposta"].startswith("Pronto! Sua consulta está marcada.")
    assert not api.horario_disponivel(proxima_semana)


def test_cenario_a_contraponto_paciente_padrao_recebe_linguagem_tecnica(api: ClinicaApi) -> None:
    headers, _ = api.cadastrar_paciente("Bruno Lima", "bruno@email.com", "77777777777")
    cardiologista = api.cadastrar_medico("Dr. João Mendes", "CRM-SP-1001", "Cardiologia")
    api.cadastrar_horario(cardiologista, "2026-11-10", "09:00")

    sugestao = api.conversa(headers).enviar("Quero agendar cardiologista na próxima semana.")

    assert sugestao["perfil"] == "PADRAO"
    assert sugestao["resultado"] == "sugestao_horario"
    assert "Cardiologia" in sugestao["resposta"]
    assert "10/11/2026 (terça-feira) às 09:00" in sugestao["resposta"]


def test_cenario_b_agendamento_completo_e_cancelamento(api: ClinicaApi) -> None:
    headers, _ = api.cadastrar_paciente("Carlos Pereira", "carlos@email.com", "66666666666")
    dra_maria = api.cadastrar_medico("Dra. Maria Silva", "CRM-SP-2002", "Clínica Geral")
    horario = api.cadastrar_horario(dra_maria, "2027-10-25", "14:00")
    conversa = api.conversa(headers)

    agendamento = conversa.enviar("Quero agendar consulta com Dra. Maria dia 25/10 às 14h")

    assert agendamento["perfil"] == "PADRAO"
    assert agendamento["resultado"] == "consulta_agendada"
    assert agendamento["consulta"]["medico_nome"] == "Dra. Maria Silva"
    assert (agendamento["consulta"]["data"], agendamento["consulta"]["hora_inicio"]) == ("2027-10-25", "14:00")
    assert "Consulta agendada com Dra. Maria Silva" in agendamento["resposta"]
    assert not api.horario_disponivel(horario)

    calendario = api.client.get("/api/consultas/minhas", headers=headers).json()
    assert [(c["data"], c["hora_inicio"], c["status"]) for c in calendario] == [("2027-10-25", "14:00", "agendada")]

    pedido = conversa.enviar("Cancelar minha consulta do dia 25/10")

    assert pedido["resultado"] == "confirmar_cancelamento"
    assert pedido["contexto"]["acao_pendente"]["tipo"] == "cancelar"
    assert "Confirma o cancelamento" in pedido["resposta"]
    assert not api.horario_disponivel(horario)

    cancelamento = conversa.enviar("sim")

    assert cancelamento["resultado"] == "consulta_cancelada"
    assert cancelamento["consulta"]["status"] == "cancelada"
    assert api.horario_disponivel(horario)
    calendario = api.client.get("/api/consultas/minhas", headers=headers).json()
    assert [c["status"] for c in calendario] == ["cancelada"]


def test_cenario_b_chat_exige_autenticacao(api: ClinicaApi) -> None:
    resposta = api.client.post("/api/assistant/chat", json={"mensagem": "oi"})

    assert resposta.status_code in (401, 403)


def test_cenario_c_chat_avisa_e_sugere_alternativa_quando_horario_e_tomado(api: ClinicaApi) -> None:
    medico = api.cadastrar_medico("Dr. João Mendes", "CRM-SP-1001", "Cardiologia")
    disputado = api.cadastrar_horario(medico, "2026-11-10", "09:00")
    alternativa = api.cadastrar_horario(medico, "2026-11-10", "10:00")
    conversas = [
        api.conversa(api.cadastrar_paciente(f"Paciente {n}", f"p{n}@email.com", f"{n:011d}")[0]) for n in (1, 2)
    ]
    for conversa in conversas:
        sugestao = conversa.enviar("Quero agendar cardiologista na próxima semana")
        assert sugestao["contexto"]["acao_pendente"]["horario_id"] == disputado

    primeira = conversas[0].enviar("sim")
    segunda = conversas[1].enviar("sim")

    assert primeira["resultado"] == "consulta_agendada"
    assert segunda["resultado"] == "sugestao_horario"
    assert segunda["resposta"].startswith(MENSAGEM_RESERVADO)
    assert segunda["contexto"]["acao_pendente"]["horario_id"] == alternativa
