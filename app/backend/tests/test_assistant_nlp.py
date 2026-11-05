from datetime import date, datetime
from zoneinfo import ZoneInfo

import pytest

from app.backend.assistant.especialidades import SINTOMAS_E_TERMOS_COLOQUIAIS, buscar_especialidade
from app.backend.assistant.nlp import Intencao, MessageInterpreter, get_language_processor
from app.backend.assistant.temporal import IntervaloDatas, TemporalResolver
from app.backend.core.clock import FixedClock


@pytest.fixture
def relogio() -> FixedClock:
    return FixedClock(datetime(2026, 11, 3, 10, 0, tzinfo=ZoneInfo("America/Sao_Paulo")))


@pytest.fixture
def interpretador(relogio: FixedClock) -> MessageInterpreter:
    return MessageInterpreter(get_language_processor(), TemporalResolver(relogio))


def test_extrai_especialidade_e_periodo_de_mensagem_com_erros(interpretador: MessageInterpreter) -> None:
    mensagem = interpretador.interpret("queria marca consulta com cardiologista pra semana q vem se der...")

    assert mensagem.intencao == Intencao.AGENDAR
    assert mensagem.entidades.especialidade == "Cardiologia"
    assert mensagem.entidades.periodo == IntervaloDatas(date(2026, 11, 9), date(2026, 11, 15))


def test_extrai_medico_data_e_hora_de_pedido_completo(interpretador: MessageInterpreter) -> None:
    entidades = interpretador.interpret("Quero agendar consulta com Dra. Maria dia 25/10 às 14h").entidades

    assert entidades.medico == "Maria"
    assert entidades.data == date(2027, 10, 25)
    assert entidades.hora == "14:00"


@pytest.mark.parametrize(
    ("texto", "intencao"),
    [
        ("Cancelar minha consulta do dia 25/10", Intencao.CANCELAR),
        ("quais são minhas consultas?", Intencao.LISTAR),
        ("quero trocar o dia da consulta", Intencao.REMARCAR),
        ("tem médico de pele essa semana?", Intencao.AGENDAR),
        ("Preciso de uma consulta de cardiologia", Intencao.AGENDAR),
        ("sim", Intencao.CONFIRMAR),
        ("não, obrigado", Intencao.NEGAR),
        ("boa tarde", Intencao.SAUDACAO),
        ("obrigada", Intencao.AGRADECIMENTO),
        ("xyz", Intencao.DESCONHECIDA),
    ],
)
def test_classifica_intencao_com_matcher_do_spacy(interpretador: MessageInterpreter, texto: str, intencao: Intencao) -> None:
    assert interpretador.interpret(texto).intencao == intencao


@pytest.mark.parametrize(
    ("texto", "especialidade"),
    [
        ("queria um médico do coração", "Cardiologia"),
        ("preciso de medico pra vista", "Oftalmologia"),
        ("consulta com ortopedista", "Ortopedia"),
        ("marcar clínico geral", "Clínica Geral"),
    ],
)
def test_reconhece_termos_leigos_e_tecnicos_de_especialidade(
    interpretador: MessageInterpreter, texto: str, especialidade: str
) -> None:
    assert interpretador.interpret(texto).entidades.especialidade == especialidade


@pytest.mark.parametrize(
    ("texto", "especialidade"),
    [
        ("quero marcar uma consulta do coração", "Cardiologia"),
        ("quero marcar uma consulta para ver minha dor nas costas", "Ortopedia"),
        ("tô com uma coceira que não passa", "Dermatologia"),
        ("não estou enxergando direito", "Oftalmologia"),
        ("preciso cuidar da minha diabetes", "Endocrinologia"),
        ("quero um médico geral", "Clínica Geral"),
        ("fazer um check-up", "Clínica Geral"),
    ],
)
def test_infere_especialidade_por_sintomas_e_termos_coloquiais(
    interpretador: MessageInterpreter, texto: str, especialidade: str
) -> None:
    mensagem = interpretador.interpret(texto)

    assert mensagem.entidades.especialidade == especialidade
    assert mensagem.intencao == Intencao.AGENDAR


def test_especialidade_explicita_prevalece_sobre_a_inferida_por_sintoma(interpretador: MessageInterpreter) -> None:
    entidades = interpretador.interpret("estou com dor de cabeça e quero um cardiologista").entidades

    assert entidades.especialidade == "Cardiologia"


def test_dicionario_de_sintomas_aponta_para_especialidades_do_catalogo() -> None:
    assert all(buscar_especialidade(nome) for nome in SINTOMAS_E_TERMOS_COLOQUIAIS)


@pytest.mark.parametrize(
    "texto", ["não sei", "sei lá", "qualquer um", "tanto faz", "geral", "qualquer médico serve"]
)
def test_detecta_quando_o_paciente_nao_tem_preferencia_de_medico(interpretador: MessageInterpreter, texto: str) -> None:
    assert interpretador.interpret(texto).sem_preferencia


def test_qualquer_dia_nao_e_confundido_com_falta_de_preferencia_de_medico(interpretador: MessageInterpreter) -> None:
    assert not interpretador.interpret("qualquer dia serve").sem_preferencia


def test_detecta_confirmacao_negacao_e_pedido_de_outra_opcao(interpretador: MessageInterpreter) -> None:
    assert interpretador.interpret("sim, pode marcar!").afirmativa
    assert interpretador.interpret("não, obrigado").negativa
    assert interpretador.interpret("tem outro horário?").pede_outra_opcao
    assert not interpretador.interpret("Quero agendar consulta com Dra. Maria dia 25/10 às 14h").afirmativa


def test_resolve_expressoes_temporais_relativas_ao_relogio(relogio: FixedClock) -> None:
    resolvedor = TemporalResolver(relogio)

    assert resolvedor.data_explicita("25/10") == date(2027, 10, 25)
    assert resolvedor.data_explicita("10/11") == date(2026, 11, 10)
    assert resolvedor.data_explicita("2026-12-02") == date(2026, 12, 2)
    assert resolvedor.data_explicita("31/02") is None
    assert resolvedor.data_relativa("amanha") == date(2026, 11, 4)
    assert resolvedor.dia_da_semana(4) == date(2026, 11, 6)
    assert resolvedor.periodo("proximo_mes") == IntervaloDatas(date(2026, 12, 1), date(2026, 12, 31))
    assert resolvedor.hora("às 3", turno="tarde") == "15:00"
    assert resolvedor.hora("14h30") == "14:30"
