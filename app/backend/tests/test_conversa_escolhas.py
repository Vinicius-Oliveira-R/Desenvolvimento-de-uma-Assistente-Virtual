"""Escolhas lidas em relação às opções exibidas: número, extenso, ordinal e referência a horário."""
import pytest

from app.backend.tests.helpers import NASCIMENTO_ADULTO, ClinicaApi


def _duas_vagas(api: ClinicaApi, nascimento: str | None = None, datas=("2026-11-10", "2026-11-10"), horas=("09:00", "14:00")):
    extra = (nascimento,) if nascimento else ()
    headers, _ = api.cadastrar_paciente("Lurdes Andrade", "lurdes@email.com", "10006172547", *extra)
    medico = api.cadastrar_medico("Dr. João Mendes", "CRM-SP-1001", "Cardiologia")
    vagas = [api.cadastrar_horario(medico, data, hora) for data, hora in zip(datas, horas)]
    return api.conversa(headers), vagas


@pytest.mark.parametrize(
    ("resposta", "indice"),
    [
        ("2", 1), ("dois", 1), ("opção dois", 1), ("a segunda", 1), ("primeira", 0), ("a primeira", 0),
        ("o das duas", 1), ("o das duas da tarde", 1), ("às 9", 0), ("o das 14h", 1), ("quero a 1", 0), ("2ª", 1),
        ("o segundo horário", 1), ("número 1", 0),
    ],
)
def test_escolha_por_numero_extenso_ordinal_ou_hora_exibida(api: ClinicaApi, resposta: str, indice: int) -> None:
    conversa, vagas = _duas_vagas(api)
    conversa.enviar("quero marcar cardiologia")

    escolha = conversa.enviar(resposta)

    pendente = escolha["contexto"]["acao_pendente"]
    assert escolha["resultado"] == "sugestao_horario"
    assert (pendente["horario_id"], pendente["aguardando_escolha"]) == (vagas[indice], False)
    assert "Ainda não marquei" in escolha["resposta"]
    assert api.consultas_no_banco() == []


def test_escolha_pelo_botao_usa_o_mesmo_validador(api: ClinicaApi) -> None:
    conversa, vagas = _duas_vagas(api)
    lista = conversa.enviar("quero marcar cardiologia")
    assert [opcao["rotulo"] for opcao in lista["opcoes"]] == ["1. Às 9h", "2. Às 14h"]

    escolha = conversa.tocar("escolher", "2")

    assert escolha["contexto"]["acao_pendente"]["horario_id"] == vagas[1]
    assert api.consultas_no_banco() == []


def test_sim_diante_de_uma_lista_pergunta_qual_horario(api: ClinicaApi) -> None:
    conversa, _ = _duas_vagas(api)
    lista = conversa.enviar("quero marcar cardiologia")

    resposta = conversa.enviar("sim")

    assert resposta["resposta"].startswith("Você disse sim; escolha um destes horários:")
    assert resposta["contexto"]["acao_pendente"] == lista["contexto"]["acao_pendente"]
    assert [opcao["codigo"] for opcao in resposta["opcoes"]] == ["escolher", "escolher"]
    assert api.consultas_no_banco() == []


@pytest.mark.parametrize("invalida", ["3", "opção 5", "a terceira", "0"])
def test_opcao_inexistente_e_explicada_com_as_opcoes_reais(api: ClinicaApi, invalida: str) -> None:
    conversa, _ = _duas_vagas(api)
    lista = conversa.enviar("quero marcar cardiologia dia 10/11")
    assert lista["contexto"]["acao_pendente"]["criterios"]["data_inicio"] == "2026-11-10"

    resposta = conversa.enviar(invalida)

    assert resposta["resposta"] == "Mostrei dois horários. Você prefere o das 9h ou o das 14h?"
    # Especialidade, data e demais critérios já informados continuam valendo.
    assert resposta["contexto"]["acao_pendente"] == lista["contexto"]["acao_pendente"]
    assert [opcao["codigo"] for opcao in resposta["opcoes"]] == ["escolher", "escolher"]
    assert api.consultas_no_banco() == []


def test_hora_que_nao_foi_mostrada_e_explicada(api: ClinicaApi) -> None:
    conversa, _ = _duas_vagas(api)
    conversa.enviar("quero marcar cardiologia")

    resposta = conversa.enviar("o das 15")

    assert resposta["resposta"] == (
        "Não mostrei horário às 15h. Mostrei dois horários. Você prefere o das 9h ou o das 14h?"
    )
    assert api.consultas_no_banco() == []


def test_segunda_ambigua_entre_opcao_e_dia_da_semana_pede_esclarecimento(api: ClinicaApi) -> None:
    conversa, vagas = _duas_vagas(api)
    conversa.enviar("quero marcar cardiologia")

    duvida = conversa.enviar("segunda")

    assert duvida["resultado"] == "esclarecer_opcao"
    assert duvida["resposta"] == (
        "Você quer o horário 2, terça-feira, 10 de novembro, às 14 horas, "
        "ou prefere procurar vaga na segunda-feira, 9 de novembro?"
    )
    assert [opcao["codigo"] for opcao in duvida["opcoes"]] == ["escolher", "buscar_dia"]
    assert api.consultas_no_banco() == []

    escolhida = conversa.enviar("a opção")
    assert escolhida["contexto"]["acao_pendente"]["horario_id"] == vagas[1]


def test_esclarecimento_pelo_dia_procura_a_segunda_feira_e_avisa_se_nao_houver(api: ClinicaApi) -> None:
    conversa, _ = _duas_vagas(api)
    conversa.enviar("quero marcar cardiologia")
    conversa.enviar("segunda")

    busca = conversa.tocar("buscar_dia")

    assert busca["resultado"] == "sugestao_horario"
    assert busca["resposta"].startswith("Não há vaga no dia 9 de novembro. Encontrei estas alternativas")
    assert api.consultas_no_banco() == []


def test_segunda_com_vaga_na_segunda_feira_e_na_posicao_dois_mostra_as_duas(api: ClinicaApi) -> None:
    conversa, vagas = _duas_vagas(api, datas=("2026-11-09", "2026-11-10"), horas=("15:00", "09:00"))
    conversa.enviar("quero marcar cardiologia")

    duvida = conversa.enviar("segunda")

    assert duvida["resultado"] == "esclarecer_opcao"
    assert duvida["contexto"]["acao_pendente"]["horarios_oferecidos"] == [vagas[1], vagas[0]]


def test_dois_horarios_iguais_mostram_o_dado_que_os_distingue(api: ClinicaApi) -> None:
    conversa, vagas = _duas_vagas(api, NASCIMENTO_ADULTO, datas=("2026-11-10", "2026-11-11"), horas=("14:00", "14:00"))
    conversa.enviar("quero marcar cardiologia")

    duvida = conversa.enviar("o das 14h")

    assert duvida["resultado"] == "esclarecer_opcao"
    assert [opcao["rotulo"] for opcao in duvida["opcoes"]] == ["1. Terça, 10/11, às 14h", "2. Quarta, 11/11, às 14h"]
    assert "10/11/2026 (terça-feira) às 14:00" in duvida["resposta"]
    assert "11/11/2026 (quarta-feira) às 14:00" in duvida["resposta"]
    assert conversa.tocar("escolher", "2")["contexto"]["acao_pendente"]["horario_id"] == vagas[1]
    assert api.consultas_no_banco() == []


def test_qualquer_um_escolhe_o_mais_proximo_e_ainda_pede_confirmacao(api: ClinicaApi) -> None:
    conversa, vagas = _duas_vagas(api)
    conversa.enviar("quero marcar cardiologia")

    escolha = conversa.enviar("tanto faz")

    assert escolha["contexto"]["acao_pendente"]["horario_id"] == vagas[0]
    assert "Escolhi o horário mais próximo." in escolha["resposta"]
    assert api.consultas_no_banco() == []


def test_na_confirmacao_e_possivel_trocar_pela_outra_opcao_da_lista(api: ClinicaApi) -> None:
    conversa, vagas = _duas_vagas(api)
    conversa.enviar("quero marcar cardiologia")
    conversa.enviar("1")

    troca = conversa.enviar("não, o das 14h")

    assert troca["contexto"]["acao_pendente"]["horario_id"] == vagas[1]
    assert api.consultas_no_banco() == []
