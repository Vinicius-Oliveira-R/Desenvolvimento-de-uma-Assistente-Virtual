"""Os dois estilos comunicam o mesmo significado: falta de profissional, falta de vaga e oferta fora do período."""
import pytest

from app.backend.tests.helpers import NASCIMENTO_ADULTO, NASCIMENTO_IDOSO, ClinicaApi

ESTILOS = [(NASCIMENTO_IDOSO, "passo_a_passo"), (NASCIMENTO_ADULTO, "direto")]


def _paciente(api: ClinicaApi, nascimento: str):
    headers, _ = api.cadastrar_paciente("Pessoa de Teste", "pessoa@example.com", "10006172547", nascimento)
    return api.conversa(headers)


@pytest.mark.parametrize(("nascimento", "estilo"), ESTILOS)
def test_especialidade_sem_profissional_cadastrado(api: ClinicaApi, nascimento: str, estilo: str) -> None:
    conversa = _paciente(api, nascimento)
    clinico = api.cadastrar_medico("Dra. Maria Silva", "CRM-PR-9911", "Clínica Geral")
    vaga = api.cadastrar_horario(clinico, "2026-11-10", "09:00")

    resposta = conversa.enviar("quero marcar dermatologista")

    texto = resposta["resposta"].lower()
    assert (resposta["resultado"], resposta["estilo"]) == ("sem_profissional", estilo)
    assert "cadastrado" in texto and ("dermatologia" in texto or "médico da pele" in texto)
    assert "vaga" not in texto
    assert [opcao["codigo"] for opcao in resposta["opcoes"]] == ["buscar_horarios", "nao_marcar"]
    assert api.consultas_no_banco() == []
    clinica_geral = conversa.tocar("buscar_horarios")
    assert clinica_geral["contexto"]["acao_pendente"]["horario_id"] == vaga


@pytest.mark.parametrize(("nascimento", "estilo"), ESTILOS)
def test_sem_vaga_no_periodo_nem_depois(api: ClinicaApi, nascimento: str, estilo: str) -> None:
    conversa = _paciente(api, nascimento)
    api.cadastrar_medico("Dr. João Mendes", "CRM-SP-1001", "Cardiologia")

    resposta = conversa.enviar("quero marcar cardiologia na semana que vem")

    texto = resposta["resposta"]
    assert (resposta["resultado"], resposta["estilo"]) == ("sem_horarios", estilo)
    assert "nem nas datas seguintes" in texto
    assert "foi marcad" in texto
    assert "cadastrado" not in texto
    assert api.consultas_no_banco() == []


@pytest.mark.parametrize(("nascimento", "estilo"), ESTILOS)
def test_oferta_fora_do_periodo_e_anunciada_antes_da_escolha(api: ClinicaApi, nascimento: str, estilo: str) -> None:
    conversa = _paciente(api, nascimento)
    medico = api.cadastrar_medico("Dr. João Mendes", "CRM-SP-1001", "Cardiologia")
    for hora in ("09:00", "14:00"):
        api.cadastrar_horario(medico, "2026-11-10", hora)

    resposta = conversa.enviar("quero marcar cardiologia amanhã")

    texto = resposta["resposta"]
    assert (resposta["resultado"], resposta["estilo"]) == ("sugestao_horario", estilo)
    primeira_opcao = texto.index("às 9 horas" if estilo == "passo_a_passo" else "09:00")
    assert texto.index("fora do período pedido") < primeira_opcao
    assert texto.startswith("Não há vaga")
    assert api.consultas_no_banco() == []


@pytest.mark.parametrize(("nascimento", "estilo"), ESTILOS)
def test_vaga_ocupada_agora_e_diferente_de_falta_de_vaga(api: ClinicaApi, nascimento: str, estilo: str) -> None:
    conversa = _paciente(api, nascimento)
    medico = api.cadastrar_medico("Dr. João Mendes", "CRM-SP-1001", "Cardiologia")
    disputada = api.cadastrar_horario(medico, "2026-11-10", "09:00")
    api.cadastrar_horario(medico, "2026-11-10", "10:00")
    conversa.enviar("quero marcar cardiologia")
    conversa.enviar("1")
    _, outro = api.cadastrar_paciente("Beto Souza", "beto@email.com", "12345678902")
    api.agendar_pela_recepcao(outro, medico, disputada, "2026-11-10")

    resposta = conversa.enviar("sim")

    assert resposta["resultado"] == "sugestao_horario"
    assert "Essa opção não está mais disponível" in resposta["resposta"]
    assert len(api.consultas_no_banco()) == 1


@pytest.mark.parametrize(("nascimento", "estilo"), ESTILOS)
def test_pedido_de_diagnostico_ou_remedio_explica_o_limite_e_oferece_agendamento(
    api: ClinicaApi, nascimento: str, estilo: str
) -> None:
    conversa = _paciente(api, nascimento)

    resposta = conversa.enviar("que doença eu tenho e qual remédio devo tomar?")

    assert (resposta["resultado"], resposta["estilo"]) == ("orientacao_medica_bloqueada", estilo)
    assert "remédio" in resposta["resposta"] or "medicamentos" in resposta["resposta"]
    assert [opcao["codigo"] for opcao in resposta["opcoes"]] == ["buscar_horarios", "nao_marcar"]
