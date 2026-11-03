"""Vetor de heurísticas inspirado nas 10 heurísticas de usabilidade de Nielsen.

Cada dimensão operacionaliza um sinal observável no texto digitado pelo paciente:

- taxa_erros (H5 prevenção de erros / H9 recuperação de erros): proporção de palavras com
  desvios ortográficos (abreviações, falta de acento, infinitivo sem "r", letras repetidas).
- complexidade (H8 estética e design minimalista): 1 - Índice de Legibilidade de Flesch
  adaptado ao português (Martins et al., 1996), limitado ao intervalo [0, 1].
- hesitacao (H1 visibilidade do status / H10 ajuda e documentação): densidade de marcadores
  de hesitação e mitigação ("se der", "acho que", "queria", reticências).
- vagueza (H6 reconhecimento em vez de memorização): proporção de referências vagas
  ("semana que vem", "qualquer dia") frente às específicas (data, hora, médico).
- informalidade (H2 correspondência com o mundo real / H4 consistência e padrões): média entre
  a densidade de coloquialismos e a escrita fora do padrão (início minúsculo ou CAIXA ALTA).
"""

import re
from dataclasses import astuple, dataclass, fields

from spacy.tokens import Doc, Token

ABREVIACOES = frozenset({
    "q", "pq", "vc", "vcs", "tb", "tbm", "hj", "dps", "msm", "td", "tds", "blz", "obg", "vlw", "cmg", "ctg",
    "qdo", "qnd", "qto", "mto", "mt", "n", "kd", "pfv", "pf", "vdd", "aki", "aq", "eh", "naum",
})
PALAVRAS_SEM_ACENTO = frozenset({
    "nao", "voce", "amanha", "medico", "medica", "horario", "horarios", "proxima", "proximo", "possivel",
    "tambem", "ja", "la", "so", "ate", "sera", "entao", "coracao", "consultorio", "clinica", "clinico",
    "sabado", "terca", "mes", "tres", "saude", "remedio", "pressao", "agradeco", "historico", "familia",
})
INFINITIVOS_SEM_R = frozenset({
    "marca", "agenda", "cancela", "desmarca", "remarca", "troca", "muda", "ve", "fala", "liga", "pega", "olha",
})
MODAIS = frozenset({
    "quero", "queria", "gostaria", "preciso", "precisava", "vou", "ia", "pode", "poderia", "podia", "posso",
    "consigo", "conseguia", "da", "quer", "devo", "pra", "para", "como",
})
COLOQUIALISMOS = frozenset({"pra", "pro", "pras", "pros", "ta", "to", "ne", "ce", "tava", "tamo", "vamo", "num", "oce"})
MARCADORES_HESITACAO: tuple[tuple[str, ...], ...] = (
    ("se", "nao", "for", "incomodo"), ("se", "for", "possivel"), ("mais", "ou", "menos"),
    ("se", "der"), ("se", "puder"), ("se", "possivel"), ("nao", "sei"), ("acho", "que"), ("sera", "que"),
    ("por", "gentileza"), ("quando", "der"),
    ("queria",), ("gostaria",), ("acho",), ("talvez",), ("poderia",), ("desculpa",), ("desculpe",),
    ("hmm",), ("hum",), ("eh",),
)
EXPRESSOES_VAGAS: tuple[tuple[str, ...], ...] = (
    ("assim", "que", "possivel"), ("o", "quanto", "antes"), ("mais", "pra", "frente"),
    ("quando", "der"), ("um", "dia"), ("qualquer",), ("algum",), ("alguma",), ("logo",),
)
ENTIDADES_ESPECIFICAS = frozenset({"DATA", "DIA_SEMANA", "HORA", "MEDICO"})
ENTIDADES_VAGAS = frozenset({"PERIODO", "TURNO"})
RETICENCIAS = frozenset({"...", "..", "…"})

_LETRA_REPETIDA = re.compile(r"([a-z])\1{2,}")
_GRUPO_VOCALICO = re.compile(r"[aeiouy]+")


@dataclass(frozen=True)
class HeuristicVector:
    taxa_erros: float
    complexidade: float
    hesitacao: float
    vagueza: float
    informalidade: float

    @classmethod
    def feature_names(cls) -> tuple[str, ...]:
        return tuple(campo.name for campo in fields(cls))

    def as_list(self) -> list[float]:
        return list(astuple(self))


class NielsenHeuristicExtractor:
    def extract(self, doc: Doc) -> HeuristicVector:
        palavras = [token for token in doc if any(caractere.isalpha() for caractere in token.text)]
        if not palavras:
            return HeuristicVector(0.0, 0.0, 0.0, 0.0, 0.0)
        normas = [token.norm_ for token in palavras]
        return HeuristicVector(
            taxa_erros=round(self._contar_desvios(palavras) / len(palavras), 4),
            complexidade=round(self._complexidade(doc, normas), 4),
            hesitacao=round(self._contar_hesitacoes(doc, normas) / len(palavras), 4),
            vagueza=round(self._vagueza(doc, normas), 4),
            informalidade=round(self._informalidade(doc, normas), 4),
        )

    @staticmethod
    def _contar_desvios(palavras: list[Token]) -> int:
        desvios = 0
        for posicao, token in enumerate(palavras):
            anterior = palavras[posicao - 1].norm_ if posicao else ""
            if (
                token.lower_ in ABREVIACOES
                or token.lower_ in PALAVRAS_SEM_ACENTO
                or (token.norm_ in INFINITIVOS_SEM_R and anterior in MODAIS)
                or _LETRA_REPETIDA.search(token.norm_)
            ):
                desvios += 1
        return desvios

    @staticmethod
    def _complexidade(doc: Doc, normas: list[str]) -> float:
        frases = max(1, sum(1 for _ in doc.sents))
        silabas = sum(max(1, len(_GRUPO_VOCALICO.findall(norma))) for norma in normas)
        flesch = 248.835 - 1.015 * (len(normas) / frases) - 84.6 * (silabas / len(normas))
        return min(1.0, max(0.0, 1 - flesch / 100))

    def _contar_hesitacoes(self, doc: Doc, normas: list[str]) -> int:
        reticencias = sum(1 for token in doc if token.text in RETICENCIAS)
        return self._contar_expressoes(normas, MARCADORES_HESITACAO) + reticencias

    def _vagueza(self, doc: Doc, normas: list[str]) -> float:
        especificas = sum(1 for ent in doc.ents if ent.label_ in ENTIDADES_ESPECIFICAS)
        vagas = sum(1 for ent in doc.ents if ent.label_ in ENTIDADES_VAGAS)
        vagas += self._contar_expressoes(normas, EXPRESSOES_VAGAS)
        total = especificas + vagas
        return vagas / total if total else 0.0

    @staticmethod
    def _informalidade(doc: Doc, normas: list[str]) -> float:
        coloquialismos = sum(1 for norma in normas if norma in COLOQUIALISMOS) / len(normas)
        letras = [caractere for caractere in doc.text if caractere.isalpha()]
        fora_do_padrao = letras[0].islower() or (len(letras) >= 4 and all(c.isupper() for c in letras))
        return 0.5 * coloquialismos + 0.5 * float(fora_do_padrao)

    @staticmethod
    def _contar_expressoes(normas: list[str], expressoes: tuple[tuple[str, ...], ...]) -> int:
        total, posicao = 0, 0
        while posicao < len(normas):
            encontrada = next(
                (expressao for expressao in expressoes if tuple(normas[posicao:posicao + len(expressao)]) == expressao),
                None,
            )
            total += encontrada is not None
            posicao += len(encontrada) if encontrada else 1
        return total
