"""Estilo inicial pela idade do cadastro, sem rótulos para o paciente e com as mesmas vagas para todos."""
from datetime import date

import pytest

from app.backend.assistant.communication_style import (
    EstadoDeEstilo,
    EstiloComunicacao,
    PedidoDeEstilo,
    PoliticaDeEstilo,
    SinaisDaMensagem,
    ler_pedido_de_estilo,
)
from app.backend.assistant.concise_responses import response_units
from app.backend.core.database import SessionLocal
from app.backend.core.idade import idade_do_cadastro, idade_em_anos
from app.backend.models import Paciente
from app.backend.tests.helpers import NASCIMENTO_ADULTO, NASCIMENTO_IDOSO, ClinicaApi

PASSO, DIRETO = EstiloComunicacao.PASSO_A_PASSO, EstiloComunicacao.DIRETO
ROTULOS_PROIBIDOS = ("idoso", "padrao", "padrão", "perfil", "probabilidade", "classificador", "faixa etária", "anos")


def assert_sem_rotulos(resposta: dict) -> None:
    assert not {"perfil", "probabilidade_idoso", "heuristicas"} & resposta.keys()
    assert not {"probabilidade_idoso", "evidencia_passo_a_passo"} & resposta["contexto"].keys()
    estado = resposta["contexto"].get("estado_estilo")
    if estado is not None:
        with pytest.raises(ValueError):
            float(estado)
    visivel = " ".join([resposta["resposta"], *(opcao["rotulo"] for opcao in resposta["opcoes"])]).lower()
    assert not [rotulo for rotulo in ROTULOS_PROIBIDOS if rotulo in visivel], visivel


def _paciente(api: ClinicaApi, nascimento: str, vagas: int = 3):
    headers, paciente_id = api.cadastrar_paciente("Pessoa de Teste", "pessoa@example.com", "10006172547", nascimento)
    medico = api.cadastrar_medico("Dra. Maria Silva", "CRM-PR-9911", "Clínica Geral")
    horarios = [api.cadastrar_horario(medico, "2026-11-10", f"{9 + i:02d}:00") for i in range(vagas)]
    return api.conversa(headers), paciente_id, horarios


@pytest.mark.parametrize(
    ("nascimento", "esperado"),
    [
        ("1966-11-04", DIRETO),  # véspera do aniversário de 60 anos (hoje é 03/11/2026): 59 anos completos
        ("1966-11-03", PASSO),  # no dia do aniversário: 60 anos
        (NASCIMENTO_IDOSO, PASSO),
        ("2001-02-03", DIRETO),
    ],
)
def test_apresentacao_inicial_usa_a_idade_em_anos_completos(api: ClinicaApi, nascimento: str, esperado) -> None:
    conversa, _, horarios = _paciente(api, nascimento)

    abertura = conversa.retomar()
    lista = conversa.tocar("marcar_consulta")

    assert abertura["estilo"] == lista["estilo"] == esperado
    assert lista["contexto"]["acao_pendente"]["horarios_oferecidos"] == horarios[: 2 if esperado == PASSO else 3]
    assert_sem_rotulos(abertura)
    assert_sem_rotulos(lista)


@pytest.mark.parametrize("valor", ["", "não informado", "31/02/1950", "1950-13-01", "2999-01-01", "1800-01-01"])
def test_cadastro_antigo_sem_data_valida_comeca_curto_e_permite_continuar(api: ClinicaApi, valor: str) -> None:
    conversa, paciente_id, horarios = _paciente(api, NASCIMENTO_ADULTO)
    with SessionLocal() as db:
        db.get(Paciente, paciente_id).data_nascimento = valor
        db.commit()

    abertura = conversa.retomar()

    assert (abertura["resultado"], abertura["estilo"]) == ("saudacao", PASSO)
    assert response_units(abertura["resposta"]) <= 3
    assert [opcao["rotulo"] for opcao in abertura["opcoes"]] == ["Marcar consulta", "Minhas consultas", "Mudar ou cancelar"]
    assert_sem_rotulos(abertura)
    conversa.tocar("marcar_consulta")
    conversa.tocar("escolher", "1")
    assert conversa.tocar("confirmar_horario")["resultado"] == "consulta_agendada"
    assert [horario for _, horario, _ in api.consultas_no_banco()] == [horarios[0]]


def test_paciente_jovem_que_nao_entende_recebe_ajuda_passo_a_passo(api: ClinicaApi) -> None:
    conversa, _, horarios = _paciente(api, "2001-02-03", vagas=8)
    lista = conversa.enviar("quero marcar consulta")
    assert lista["estilo"] == DIRETO and lista["contexto"]["acao_pendente"]["horarios_oferecidos"] == horarios[:6]

    ajuda = conversa.enviar("não entendi")

    assert ajuda["estilo"] == PASSO
    assert ajuda["resposta"].startswith("Calma, vou repetir.")
    assert "às 9 horas" in ajuda["resposta"]
    # A dúvida preserva a pergunta: mesmas opções e mesma proposta (os botões já exibidos continuam valendo).
    assert ajuda["contexto"]["acao_pendente"] == lista["contexto"]["acao_pendente"]
    assert_sem_rotulos(ajuda)
    # Daqui em diante as novas páginas vêm de duas em duas.
    assert conversa.enviar("mais horários")["contexto"]["acao_pendente"]["horarios_oferecidos"] == horarios[6:8]
    assert api.consultas_no_banco() == []


@pytest.mark.parametrize(("nascimento", "esperado"), [(NASCIMENTO_ADULTO, DIRETO), (NASCIMENTO_IDOSO, PASSO)])
def test_respostas_curtas_nao_mudam_o_estilo(api: ClinicaApi, nascimento: str, esperado) -> None:
    conversa, _, _ = _paciente(api, nascimento)
    for mensagem in ("oi", "olá", "bom dia", "obrigado", "ok", "2"):
        assert conversa.enviar(mensagem)["estilo"] == esperado, mensagem


def test_pedidos_naturais_mudam_a_explicacao_e_reapresentam_a_pergunta(api: ClinicaApi) -> None:
    conversa, _, horarios = _paciente(api, NASCIMENTO_ADULTO)
    lista = conversa.enviar("quero marcar consulta")

    partes = conversa.enviar("vá por partes")
    direto = conversa.enviar("seja mais direto")
    melhor = conversa.enviar("explique melhor")
    automatico = conversa.enviar("modo automático")

    assert (partes["estilo"], direto["estilo"], melhor["estilo"]) == (PASSO, DIRETO, PASSO)
    assert partes["resposta"].startswith("Certo, vou explicar passo a passo.")
    assert direto["resposta"].startswith("Certo, serei mais direto.")
    assert "ajustar" in automatico["resposta"]
    for resposta in (partes, direto, melhor, automatico):
        assert resposta["resultado"] == "sugestao_horario"
        assert resposta["contexto"]["acao_pendente"]["horarios_oferecidos"] == horarios
        assert resposta["contexto"]["acao_pendente"]["proposta"] == lista["contexto"]["acao_pendente"]["proposta"]
        assert_sem_rotulos(resposta)
    assert api.consultas_no_banco() == []


def test_mostre_mais_horarios_amplia_a_lista_sem_perder_as_opcoes_atuais(api: ClinicaApi) -> None:
    conversa, _, horarios = _paciente(api, NASCIMENTO_IDOSO, vagas=5)
    lista = conversa.enviar("quero marcar consulta")
    assert lista["contexto"]["acao_pendente"]["horarios_oferecidos"] == horarios[:2]

    ampliada = conversa.enviar("mostre mais horários")

    assert ampliada["estilo"] == PASSO
    assert ampliada["resposta"].startswith("Certo, vou mostrar mais horários de cada vez.")
    assert ampliada["contexto"]["acao_pendente"]["horarios_oferecidos"] == horarios
    assert api.consultas_no_banco() == []


@pytest.mark.parametrize(
    ("comando", "esperado"),
    [("modo simples", PASSO), ("fale simples", PASSO), ("linguagem simples", PASSO), ("modo padrão", DIRETO),
     ("linguagem padrão", DIRETO)],
)
def test_comandos_de_estilo_existentes_continuam_validos(api: ClinicaApi, comando: str, esperado) -> None:
    conversa, _, _ = _paciente(api, NASCIMENTO_ADULTO if esperado == PASSO else NASCIMENTO_IDOSO)

    resposta = conversa.enviar(comando)

    assert resposta["estilo"] == esperado
    assert_sem_rotulos(resposta)


def test_contexto_devolvido_nao_revela_a_faixa_etaria(api: ClinicaApi) -> None:
    contextos = []
    for indice, nascimento in enumerate(("1966-11-04", "1966-11-03")):
        headers, _ = api.cadastrar_paciente(f"Pessoa {indice}", f"p{indice}@example.com", f"1000617254{7 + indice}", nascimento)
        contextos.append(api.conversa(headers).retomar()["contexto"])

    assert [contexto["estilo"] for contexto in contextos] == [DIRETO, PASSO]
    assert contextos[0].keys() == contextos[1].keys()
    for contexto in contextos:
        with pytest.raises(ValueError):
            float(contexto["estado_estilo"])


def test_os_dois_estilos_recebem_as_mesmas_vagas_e_operacoes(api: ClinicaApi) -> None:
    jovem, _ = api.cadastrar_paciente("Ana", "ana@example.com", "10006172547", NASCIMENTO_ADULTO)
    idosa, _ = api.cadastrar_paciente("Lurdes", "lurdes@example.com", "10008641544", NASCIMENTO_IDOSO)
    medico = api.cadastrar_medico("Dra. Maria Silva", "CRM-PR-9911", "Clínica Geral")
    horarios = [api.cadastrar_horario(medico, "2026-11-10", f"{9 + i:02d}:00") for i in range(3)]

    listas = [api.conversa(headers).enviar("quero marcar consulta") for headers in (jovem, idosa)]

    assert [lista["estilo"] for lista in listas] == [DIRETO, PASSO]
    assert [lista["contexto"]["acao_pendente"]["horarios_oferecidos"][0] for lista in listas] == [horarios[0]] * 2
    assert {opcao["codigo"] for opcao in listas[0]["opcoes"]} >= {opcao["codigo"] for opcao in listas[1]["opcoes"]}


# ------------------------------------------------------------------ unidades
@pytest.mark.parametrize(
    ("nascimento", "hoje", "idade"),
    [
        (date(1966, 11, 4), date(2026, 11, 3), 59),
        (date(1966, 11, 3), date(2026, 11, 3), 60),
        (date(1964, 2, 29), date(2025, 2, 28), 60),
        (date(1964, 2, 29), date(2025, 3, 1), 61),
    ],
)
def test_idade_em_anos_completos_considera_o_aniversario(nascimento: date, hoje: date, idade: int) -> None:
    assert idade_em_anos(nascimento, hoje) == idade


@pytest.mark.parametrize(
    ("valor", "idade"), [("1966-11-03", 60), ("03/11/1966", 60), ("", None), ("sem data", None), ("2027-01-01", None)]
)
def test_idade_do_cadastro_aceita_formatos_conhecidos_e_rejeita_o_resto(valor: str, idade: int | None) -> None:
    assert idade_do_cadastro(valor, date(2026, 11, 3)) == idade


def test_limiar_de_idade_e_configuravel() -> None:
    assert PoliticaDeEstilo(65).inicial(62) == DIRETO
    assert PoliticaDeEstilo(60).inicial(62) == PASSO
    assert PoliticaDeEstilo(60).inicial(None) == PASSO


def test_classificador_nao_muda_o_estilo_por_uma_mensagem_e_exige_evidencia_continua() -> None:
    politica = PoliticaDeEstilo(60)
    estado = politica.decidir(EstadoDeEstilo(), 72, SinaisDaMensagem()).estado
    longa_e_fluente = SinaisDaMensagem(palavras=10, previsao_passo_a_passo=0.05)
    estilos = []
    for _ in range(3):
        decisao = politica.decidir(estado, 72, longa_e_fluente)
        estado = decisao.estado
        estilos.append(decisao.estilo)
    assert estilos == [PASSO, PASSO, DIRETO]
    curta = SinaisDaMensagem(palavras=1, previsao_passo_a_passo=1.0)
    assert politica.decidir(estado, 72, curta).estilo == DIRETO


def test_pedido_explicito_e_ajuda_tem_prioridade_sobre_o_classificador() -> None:
    politica = PoliticaDeEstilo(60)
    jovem = politica.decidir(EstadoDeEstilo(), 25, SinaisDaMensagem()).estado
    assert politica.decidir(jovem, 25, SinaisDaMensagem(pediu_ajuda=True, palavras=2)).estilo == PASSO
    simples = politica.decidir(jovem, 25, SinaisDaMensagem(pedido=PedidoDeEstilo.PASSO_A_PASSO)).estado
    fluente = SinaisDaMensagem(palavras=12, previsao_passo_a_passo=0.0)
    assert politica.decidir(simples, 25, fluente).estilo == PASSO
    mais = politica.decidir(simples, 25, SinaisDaMensagem(pedido=PedidoDeEstilo.MAIS_OPCOES))
    assert (mais.estilo, mais.opcoes_por_vez) == (PASSO, 6)


@pytest.mark.parametrize(
    ("texto", "pedido"),
    [("Explique melhor", PedidoDeEstilo.PASSO_A_PASSO), ("vá por partes!", PedidoDeEstilo.PASSO_A_PASSO),
     ("seja mais direto", PedidoDeEstilo.DIRETO), ("Mostre mais horários", PedidoDeEstilo.MAIS_OPCOES),
     ("modo automático", PedidoDeEstilo.AUTOMATICO), ("mais horários na sexta", None), ("oi", None)],
)
def test_leitura_dos_pedidos_de_estilo(texto: str, pedido) -> None:
    assert ler_pedido_de_estilo(texto) == pedido
