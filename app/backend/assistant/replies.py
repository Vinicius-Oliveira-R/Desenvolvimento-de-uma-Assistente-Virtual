"""Leitura da resposta do paciente diante da pergunta pendente.

Autorizar uma alteração exige a frase inteira de concordância ("sim", "pode marcar",
"confirmo") ou o botão nomeado da ação. Perguntas, dúvidas e frases que só começam com
"pode"/"quero" ("pode repetir?", "quero entender") nunca autorizam: a etapa é reapresentada.
Escolhas são lidas em relação às opções exibidas, nunca a uma lista imaginada.
"""
import re
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import date
from enum import StrEnum
from typing import Protocol

from app.backend.assistant.nlp import Entidades, Intencao
from app.backend.assistant.temporal import TURNOS
from app.backend.core.text import normalizar, normalizar_frase


class Verbo(StrEnum):
    AGENDAR = "agendar"
    REMARCAR = "remarcar"
    CANCELAR = "cancelar"


class TipoLeitura(StrEnum):
    CONFIRMA = "confirma"
    NEGA = "nega"
    DUVIDA = "duvida"
    SOCIAL = "social"
    ESCOLHA = "escolha"
    AMBIGUA = "ambigua"
    OPCAO_INEXISTENTE = "opcao_inexistente"
    OUTRA_OPCAO = "outra_opcao"
    BUSCAR_DIA = "buscar_dia"
    NENHUMA = "nenhuma"


@dataclass(frozen=True)
class Leitura:
    tipo: TipoLeitura
    indices: tuple[int, ...] = ()
    numero: int | None = None
    hora: str | None = None
    dia: date | None = None
    automatica: bool = False
    sobre_situacao: bool = False


NENHUMA = Leitura(TipoLeitura.NENHUMA)


class OpcaoExibida(Protocol):
    data: date
    hora: str
    medico: str


@dataclass(frozen=True)
class ContextoDaLeitura:
    verbo: Verbo
    opcoes: Sequence[OpcaoExibida | None] = ()
    opcoes_sao_horarios: bool = True
    escolhendo: bool = False
    confirmando: bool = False
    duvida_opcao: int | None = None
    duvida_dia: date | None = None


_CONFIRMA = frozenset({
    "sim", "s", "ss", "sim sim", "isso", "isso mesmo", "isso ai", "exato", "confirmo", "confirmar", "confirma",
    "confirmado", "sim confirmo", "pode", "pode sim", "sim pode", "pode ser", "pode confirmar", "sim pode confirmar",
    "ok", "okay", "certo", "claro", "claro que sim", "sim claro", "com certeza", "beleza", "blz", "fechado",
    "combinado", "perfeito", "otimo", "positivo", "aceito", "sim aceito", "quero", "quero sim", "sim quero",
    "ta bom", "esta bom", "ta bem", "esta bem", "bora", "vamos",
})
_CONFIRMA_POR_VERBO = {
    Verbo.AGENDAR: frozenset({
        "marcar", "marca", "marque", "pode marcar", "sim pode marcar", "sim marca", "quero marcar", "agendar",
        "agenda", "agende", "pode agendar", "confirmar horario", "confirmo o horario", "confirma o horario",
        "esse", "este", "esse mesmo", "este mesmo", "quero esse", "quero este", "pode ser esse", "pode ser este",
        "pode marcar esse", "marca esse", "fico com esse",
    }),
    Verbo.REMARCAR: frozenset({
        "trocar", "troca", "troque", "pode trocar", "sim pode trocar", "quero trocar", "mudar", "muda", "mude",
        "pode mudar", "remarcar", "remarca", "pode remarcar", "confirmar troca", "confirmo a troca",
        "confirma a troca", "aceito a troca", "aceito a mudanca", "pode fazer a troca",
    }),
    Verbo.CANCELAR: frozenset({
        "desmarcar", "desmarca", "desmarque", "pode desmarcar", "sim pode desmarcar", "quero desmarcar",
        "cancelar", "cancela", "cancele", "pode cancelar", "quero cancelar", "desmarcar consulta",
        "desmarcar a consulta", "cancelar consulta", "cancelar a consulta", "confirmo o cancelamento",
        "confirmar cancelamento", "aceito o cancelamento",
    }),
}
_NEGA = frozenset({
    "nao", "n", "nao quero", "agora nao", "melhor nao", "deixa", "deixa pra la", "deixa para la", "desisto",
    "nao precisa", "negativo", "nao nao", "nao pode", "nao aceito", "recuso", "nao confirmo", "nem pensar",
    "de jeito nenhum",
})
_MANTER = frozenset({
    "manter", "manter minha consulta", "manter a consulta", "manter consulta", "mantenha", "mantem", "quero manter",
    "pode manter", "deixa como esta", "deixa como ta", "deixa assim", "fica como esta", "fica assim",
})
_NEGA_POR_VERBO = {
    Verbo.AGENDAR: frozenset({
        "nao marcar", "nao marque", "nao quero marcar", "nao quero agendar", "nao marcar agora", "nao agendar",
        "nao marcar nada", "nenhum", "nenhuma", "cancela", "cancelar", "pode cancelar",
    }),
    Verbo.REMARCAR: _MANTER | {"nao trocar", "nao troca", "nao quero trocar", "nao mudar", "nao muda", "nao remarcar"},
    Verbo.CANCELAR: _MANTER | {
        "nao desmarcar", "nao desmarca", "nao desmarque", "nao quero desmarcar", "nao cancelar", "nao cancela",
        "nao quero cancelar",
    },
}
_OUTRA = frozenset({
    "outro", "outra", "outros", "outras", "outro horario", "outra opcao", "outros horarios", "outras opcoes",
    "esse nao", "este nao", "nao quero esse", "nao quero este", "nao gostei", "nenhum desses", "nenhum deles",
    "ver outro", "ver outros", "quero outro", "tem outro", "tem outros", "proximo", "proxima", "mais horarios",
    "mais opcoes", "mais vagas", "ver outro horario", "escolher outro horario", "outro dia",
})
_SEM_PREFERENCIA_DE_HORARIO = frozenset({
    "tanto faz", "qualquer um", "qualquer uma", "qualquer", "qualquer horario", "qualquer dia", "o mais cedo",
    "mais cedo", "o mais proximo", "mais proximo", "o primeiro que tiver", "o mais rapido", "voce escolhe",
    "vc escolhe", "pode escolher", "escolhe voce", "o que tiver", "o mais cedo possivel",
})
_EXPLICACAO = re.compile(
    r"\b(?:pode repetir|repete|repita|repetir|de novo|outra vez|como assim|nao entendi|nao entendo|nao compreendi"
    r"|nao estou entendendo|nao to entendendo|confus[oa]|quero entender|entender melhor|explica|explique|explicar"
    r"|o que (?:e|eu faco|faco|significa|quer dizer|acontece)|que quer dizer|como (?:eu )?(?:faco|funciona)|e agora|hein"
    r"|me ajuda|ajuda|socorro|perdid[oa])\b"
)
_INCERTEZA = re.compile(r"\b(?:nao sei|nem sei|sei la|nao lembro|nao tenho certeza)\b")
_SITUACAO = re.compile(
    r"\b(?:ja )?(?:esta|ta|ficou|foi|fica)\s+(?:ja\s+)?(?:marcad|agendad|confirmad|desmarcad|cancelad|trocad|remarcad|mudad)[oa]\b"
    r"|\bja (?:marcou|marquei|agendou|confirmou|desmarcou|cancelou|trocou)\b|\b(?:marcou|confirmou)\b"
)
_VERBOS = {
    Verbo.AGENDAR: "marcar|marca|marque|agendar|agenda|agende",
    Verbo.REMARCAR: "trocar|troca|troque|mudar|muda|mude|remarcar|remarca|remarque|reagendar|reagenda|reagende",
    Verbo.CANCELAR: "desmarcar|desmarca|desmarque|cancelar|cancela|cancele",
}
_COMPLEMENTO = (
    r"(?: (?:sim|a consulta|minha consulta|a minha consulta|o horario|esse horario|este horario|esse|este|a troca|agora))?"
)
# "Sim, pode remarcar", "aceito cancelar", "não quero trocar": o verbo precisa ser o da pergunta atual.
_CONFIRMA_COM_VERBO = {
    verbo: re.compile(
        rf"^(?:(?:sim|isso|ok|claro) )?(?:(?:pode|pode sim|sim pode|quero|aceito|confirmo|vamos) )?(?:{verbos}){_COMPLEMENTO}$"
    )
    for verbo, verbos in _VERBOS.items()
}
_NEGA_COM_VERBO = {
    verbo: re.compile(rf"^nao (?:(?:quero|precisa|pode|vou|quero mais|precisa mais) )?(?:{verbos}){_COMPLEMENTO}$")
    for verbo, verbos in _VERBOS.items()
}
_PEDE_MAIS = re.compile(r"\b(?:outr[oa]s?|mais)\b")
_ACOES_EXPLICITAS = (Intencao.CANCELAR, Intencao.REMARCAR, Intencao.LISTAR, Intencao.ORIENTACAO_MEDICA)
_RESPOSTAS_NEUTRAS = (Intencao.DESCONHECIDA, Intencao.CONFIRMAR, Intencao.NEGAR)

_ORDINAIS = {
    "primeiro": 1, "primeira": 1, "segundo": 2, "segunda": 2, "terceiro": 3, "terceira": 3,
    "quarto": 4, "quarta": 4, "quinto": 5, "quinta": 5, "sexto": 6, "sexta": 6,
}
_CARDINAIS = {"um": 1, "uma": 1, "dois": 2, "duas": 2, "tres": 3, "quatro": 4, "cinco": 5, "seis": 6}
_DIA_DO_ORDINAL = {"segunda": 0, "quarta": 2, "quinta": 3, "sexta": 4}
_PREFIXOS_DE_ESCOLHA = tuple(sorted(
    ("eu quero", "eu prefiro", "eu escolho", "quero", "prefiro", "escolho", "vou querer", "pode ser", "fico com",
     "vou de", "pode marcar", "marca", "marque", "marcar", "sim", "entao", "e"),
    key=len, reverse=True,
))
_ROTULOS_DE_OPCAO = ("opcao", "numero", "item", "n", "no")
_SUFIXOS_DE_OPCAO = frozenset({"opcao", "horario", "vaga", "consulta", "da lista", "mesmo", "ai", "ali"})
_HORAS_POR_EXTENSO = {
    "uma": 1, "duas": 2, "tres": 3, "quatro": 4, "cinco": 5, "seis": 6, "sete": 7, "oito": 8, "nove": 9,
    "dez": 10, "onze": 11, "doze": 12,
}
_REFERENCIA_DE_HORA = re.compile(
    r"\b(?:(?:as|a|das|da|de|pras|pelas)\s+(?P<num>\d{1,2})(?:\s*(?:h|:)\s*(?P<min>\d{2}))?"
    r"|(?:as|a|das|da|pras|pelas)\s+(?P<ext>" + "|".join(_HORAS_POR_EXTENSO) + r"|meio dia|meio-dia)"
    r"|(?P<solta>\d{1,2})\s*(?:h\s*(?P<min_solta>\d{2})?|:(?P<min_dois_pontos>\d{2}))(?!\d))"
    r"(?:\s*(?:h|hs|hrs|horas?)\b)?(?:\s+(?:da|de|pela|a)\s+(?P<turno>manha|tarde|noite))?"
)
_FORMA_DE_REFERENCIA = re.compile(r"^(?:(?:quero|prefiro|escolho|pode ser|fico com|sim)\s+)?(?:o|a)\s+(?:d[aeo]s?|com)\b")


@dataclass(frozen=True)
class _NumeroEscolhido:
    valor: int
    dia_ambiguo: int | None


@dataclass(frozen=True)
class _HoraMencionada:
    horas: frozenset[int]
    minuto: int | None
    texto: str


def pede_explicacao(texto: str) -> bool:
    """Dificuldade de compreensão: muda o estilo para passo a passo e reapresenta a etapa."""
    return texto.strip(" ?") == "" and "?" in texto or bool(_EXPLICACAO.search(normalizar_frase(texto)))


class LeitorDeRespostas:
    def __init__(self, proxima_data_do_dia: Callable[[int], date]):
        self._proxima_data_do_dia = proxima_data_do_dia

    def ler(self, texto: str, intencao: Intencao, entidades: Entidades, contexto: ContextoDaLeitura) -> Leitura:
        frase = normalizar_frase(texto)
        pergunta = "?" in texto
        if not frase:
            return Leitura(TipoLeitura.DUVIDA) if pergunta else NENHUMA
        if contexto.duvida_dia and (resolvida := self._resolver_duvida(frase, contexto)):
            return resolvida
        # A dúvida vale mesmo com verbo de ação: "não sei se quero cancelar" não troca de assunto.
        if leitura := self._duvida(frase, entidades):
            return leitura
        if contexto.opcoes and (escolha := self._escolha(frase, entidades, intencao, contexto)):
            return escolha
        if not pergunta:
            if self._concorda(frase, contexto.verbo):
                return Leitura(TipoLeitura.CONFIRMA)
            if frase in _NEGA or frase in _NEGA_POR_VERBO[contexto.verbo] or _NEGA_COM_VERBO[contexto.verbo].match(frase):
                return Leitura(TipoLeitura.NEGA)
            if contexto.verbo != Verbo.CANCELAR and frase in _OUTRA:
                return Leitura(TipoLeitura.OUTRA_OPCAO)
        if intencao in (Intencao.SAUDACAO, Intencao.AGRADECIMENTO) and len(frase.split()) <= 4:
            return Leitura(TipoLeitura.SOCIAL)
        if pergunta and not entidades.possui_criterios and not _PEDE_MAIS.search(frase):
            # Diante de uma confirmação, "pode marcar?" é dúvida; só pedir a lista de consultas muda de assunto.
            if intencao in _RESPOSTAS_NEUTRAS or (contexto.confirmando and intencao != Intencao.LISTAR):
                return Leitura(TipoLeitura.DUVIDA)
        return NENHUMA

    @staticmethod
    def _concorda(frase: str, verbo: Verbo) -> bool:
        return frase in _CONFIRMA or frase in _CONFIRMA_POR_VERBO[verbo] or bool(_CONFIRMA_COM_VERBO[verbo].match(frase))

    @staticmethod
    def _duvida(frase: str, entidades: Entidades) -> Leitura | None:
        situacao = bool(_SITUACAO.search(frase))
        if situacao or _EXPLICACAO.search(frase):
            return Leitura(TipoLeitura.DUVIDA, sobre_situacao=situacao)
        if _INCERTEZA.search(frase) and not entidades.especialidade:
            return Leitura(TipoLeitura.DUVIDA)
        return None

    def _escolha(
        self, frase: str, entidades: Entidades, intencao: Intencao, contexto: ContextoDaLeitura
    ) -> Leitura | None:
        total = len(contexto.opcoes)
        if numero := _numero_escolhido(frase):
            if numero.dia_ambiguo is not None and not (total >= 2 and numero.valor <= total):
                return None
            if numero.dia_ambiguo is not None:
                return self._entre_opcao_e_dia(numero, contexto)
            if 1 <= numero.valor <= total:
                return Leitura(TipoLeitura.ESCOLHA, indices=(numero.valor,))
            return Leitura(TipoLeitura.OPCAO_INEXISTENTE, numero=numero.valor)
        if contexto.escolhendo and frase in _SEM_PREFERENCIA_DE_HORARIO:
            return Leitura(TipoLeitura.ESCOLHA, indices=(1,), automatica=True)
        if intencao in _ACOES_EXPLICITAS or entidades.especialidade:
            return None
        hora = _hora_mencionada(frase)
        if hora is None and not (entidades.data or entidades.dia_semana is not None or entidades.medico or entidades.turno):
            return None
        indices = tuple(
            posicao for posicao, opcao in enumerate(contexto.opcoes, start=1)
            if opcao is not None and _corresponde(opcao, hora, entidades)
        )
        if len(indices) == 1:
            return Leitura(TipoLeitura.ESCOLHA, indices=indices)
        if indices:
            return Leitura(TipoLeitura.AMBIGUA, indices=indices)
        if _FORMA_DE_REFERENCIA.match(frase):
            return Leitura(TipoLeitura.OPCAO_INEXISTENTE, hora=hora.texto if hora else None)
        return None

    def _entre_opcao_e_dia(self, numero: _NumeroEscolhido, contexto: ContextoDaLeitura) -> Leitura:
        no_dia = tuple(
            posicao for posicao, opcao in enumerate(contexto.opcoes, start=1)
            if opcao is not None and opcao.data.weekday() == numero.dia_ambiguo
        )
        if no_dia == (numero.valor,):
            return Leitura(TipoLeitura.ESCOLHA, indices=no_dia)
        if no_dia:
            return Leitura(TipoLeitura.AMBIGUA, indices=tuple(dict.fromkeys((numero.valor, *no_dia))))
        dia = self._proxima_data_do_dia(numero.dia_ambiguo)
        return Leitura(TipoLeitura.AMBIGUA, indices=(numero.valor,), dia=dia)

    @staticmethod
    def _resolver_duvida(frase: str, contexto: ContextoDaLeitura) -> Leitura | None:
        palavras = [palavra for palavra in frase.split() if palavra not in ("na", "no", "pra", "para", "a", "o", "feira")]
        dia = " ".join(palavras)
        if dia in ("dia", "data", "procurar", "o dia", "dia da semana") or (
            _DIA_DO_ORDINAL.get(dia) == contexto.duvida_dia.weekday()
        ):
            return Leitura(TipoLeitura.BUSCAR_DIA, dia=contexto.duvida_dia)
        valida = contexto.duvida_opcao is not None and 1 <= contexto.duvida_opcao <= len(contexto.opcoes)
        if valida and dia in ("opcao", "horario", "esse horario", "opcao da lista", "da lista", "lista"):
            return Leitura(TipoLeitura.ESCOLHA, indices=(contexto.duvida_opcao,))
        return None


def _numero_escolhido(frase: str) -> _NumeroEscolhido | None:
    palavras = _sem_prefixos(frase.split())
    marcado = False
    if palavras[:1] in (["a"], ["o"]):
        palavras, marcado = palavras[1:], True
    if palavras[:1] and palavras[0] in _ROTULOS_DE_OPCAO:
        palavras, marcado = palavras[1:], True
    if not palavras:
        return None
    token, resto = palavras[0], palavras[1:]
    if digitos := re.fullmatch(r"(\d{1,2})(?:a|o)?", token):
        valor, marcado = int(digitos[1]), True
    elif token in _ORDINAIS:
        valor = _ORDINAIS[token]
    elif token in _CARDINAIS and (token not in ("um", "uma") or marcado or not resto):
        valor, marcado = _CARDINAIS[token], True
    else:
        return None
    if resto and " ".join(resto) not in _SUFIXOS_DE_OPCAO:
        return None
    marcado = marcado or bool(resto)
    return _NumeroEscolhido(valor, None if marcado else _DIA_DO_ORDINAL.get(token))


def _sem_prefixos(palavras: list[str]) -> list[str]:
    for prefixo in _PREFIXOS_DE_ESCOLHA:
        partes = prefixo.split()
        if palavras[:len(partes)] == partes and len(palavras) > len(partes):
            return _sem_prefixos(palavras[len(partes):])
    return palavras


def _hora_mencionada(frase: str) -> _HoraMencionada | None:
    if not (achado := _REFERENCIA_DE_HORA.search(frase)):
        return None
    if achado["ext"]:
        hora = 12 if achado["ext"].startswith("meio") else _HORAS_POR_EXTENSO[achado["ext"]]
        minuto = None
    else:
        hora = int(achado["num"] or achado["solta"])
        minuto_texto = achado["min"] or achado["min_solta"] or achado["min_dois_pontos"]
        minuto = int(minuto_texto) if minuto_texto else None
    if hora > 23 or (minuto is not None and minuto > 59):
        return None
    turno = achado["turno"]
    if turno in ("tarde", "noite") and hora < 12:
        horas = frozenset({hora + 12})
    elif turno == "manha" or hora >= 12 or hora == 0:
        horas = frozenset({hora})
    else:
        horas = frozenset({hora, hora + 12})
    texto = f"{min(horas)}h{minuto:02d}" if minuto else f"{min(horas) if len(horas) == 1 else hora}h"
    return _HoraMencionada(horas, minuto, texto)


def _corresponde(opcao: OpcaoExibida, hora: _HoraMencionada | None, entidades: Entidades) -> bool:
    horas, minutos = (int(parte) for parte in opcao.hora.split(":"))
    if hora and (horas not in hora.horas or (hora.minuto is not None and minutos != hora.minuto)):
        return False
    if entidades.dia_semana is not None:
        if opcao.data.weekday() != entidades.dia_semana:
            return False
    elif entidades.data and opcao.data != entidades.data:
        return False
    if entidades.periodo and not entidades.periodo.inicio <= opcao.data <= entidades.periodo.fim:
        return False
    if entidades.turno and (faixa := TURNOS.get(entidades.turno)) and not faixa[0] <= opcao.hora < faixa[1]:
        return False
    return not entidades.medico or normalizar(entidades.medico) in normalizar(opcao.medico)
