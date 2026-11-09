import threading
from dataclasses import dataclass, fields
from datetime import date
from enum import StrEnum
from functools import lru_cache
from typing import Any

import spacy
from spacy.language import Language
from spacy.matcher import Matcher
from spacy.symbols import ORTH
from spacy.tokens import Doc, Span

from app.backend.assistant.patterns import (
    PADROES_SINAIS,
    SINAL_AFIRMACAO,
    SINAL_AFIRMACAO_INICIAL,
    SINAL_MENCAO_CONSULTA,
    SINAL_NEGACAO,
    SINAL_OUTRA_OPCAO,
    SINAL_SEM_PREFERENCIA,
    TITULOS_MEDICOS,
    padroes_entidades,
)
from app.backend.assistant.temporal import IntervaloDatas, TemporalResolver
from app.backend.core.text import normalizar


class Intencao(StrEnum):
    AGENDAR = "agendar"
    CANCELAR = "cancelar"
    REMARCAR = "remarcar"
    LISTAR = "listar"
    ORIENTACAO_MEDICA = "orientacao_medica"
    CONFIRMAR = "confirmar"
    NEGAR = "negar"
    SAUDACAO = "saudacao"
    AGRADECIMENTO = "agradecimento"
    DESCONHECIDA = "desconhecida"


INTENCOES_DE_ACAO = (Intencao.CANCELAR, Intencao.REMARCAR, Intencao.AGENDAR, Intencao.LISTAR)
INTENCOES_DE_RESPOSTA = (Intencao.CONFIRMAR, Intencao.NEGAR)
INTENCOES_SOCIAIS = (Intencao.SAUDACAO, Intencao.AGRADECIMENTO)


@Language.component("normalizador_pt")
def normalizador_pt(doc: Doc) -> Doc:
    for token in doc:
        token.norm_ = normalizar(token.text)
    return doc


class LanguageProcessor:
    ABREVIACOES_COM_PONTO = ("dr.", "dra.", "sr.", "sra.")

    def __init__(self) -> None:
        self._nlp = spacy.blank("pt")
        for abreviacao in self.ABREVIACOES_COM_PONTO:
            for variante in {abreviacao, abreviacao.capitalize(), abreviacao.upper()}:
                self._nlp.tokenizer.add_special_case(variante, [{ORTH: variante}])
        self._nlp.add_pipe("normalizador_pt")
        self._nlp.add_pipe("sentencizer")
        self._nlp.add_pipe("entity_ruler").add_patterns(padroes_entidades())
        self._matcher = Matcher(self._nlp.vocab)
        for rotulo, padroes in PADROES_SINAIS.items():
            self._matcher.add(rotulo, padroes)
        self._lock = threading.Lock()

    def process(self, texto: str) -> Doc:
        with self._lock:
            return self._nlp(texto)

    def analyze(self, texto: str) -> tuple[Doc, dict[str, list[int]]]:
        with self._lock:
            doc = self._nlp(texto)
            ocorrencias = self._matcher(doc)
        sinais: dict[str, list[int]] = {}
        for match_id, inicio, _ in ocorrencias:
            sinais.setdefault(self._nlp.vocab.strings[match_id], []).append(inicio)
        return doc, sinais


@lru_cache
def get_language_processor() -> LanguageProcessor:
    return LanguageProcessor()


@dataclass(frozen=True)
class Entidades:
    especialidade: str | None = None
    medico: str | None = None
    data: date | None = None
    periodo: IntervaloDatas | None = None
    hora: str | None = None
    turno: str | None = None

    @property
    def possui_criterios(self) -> bool:
        return any(getattr(self, campo.name) is not None for campo in fields(self))

    def as_dict(self) -> dict[str, Any]:
        return {
            "especialidade": self.especialidade,
            "medico": self.medico,
            "data": self.data.isoformat() if self.data else None,
            "periodo": (
                {"inicio": self.periodo.inicio.isoformat(), "fim": self.periodo.fim.isoformat()}
                if self.periodo
                else None
            ),
            "hora": self.hora,
            "turno": self.turno,
        }


@dataclass(frozen=True)
class MensagemInterpretada:
    texto: str
    doc: Doc
    intencao: Intencao
    entidades: Entidades
    total_palavras: int
    afirmativa: bool = False
    negativa: bool = False
    pede_outra_opcao: bool = False
    sem_preferencia: bool = False


class MessageInterpreter:
    LIMITE_RESPOSTA_CURTA = 6

    def __init__(self, processor: LanguageProcessor, resolver: TemporalResolver):
        self._processor = processor
        self._resolver = resolver

    def interpret(self, texto: str) -> MensagemInterpretada:
        doc, sinais = self._processor.analyze(texto)
        entidades = self._extrair_entidades(doc)
        palavras = [token for token in doc if not (token.is_punct or token.is_space)]
        curta = len(palavras) <= self.LIMITE_RESPOSTA_CURTA
        inicio = palavras[0].i if palavras else 0
        afirmativa = curta and (SINAL_AFIRMACAO in sinais or inicio in sinais.get(SINAL_AFIRMACAO_INICIAL, []))
        negativa = curta and inicio in sinais.get(SINAL_NEGACAO, [])
        return MensagemInterpretada(
            texto=texto,
            doc=doc,
            intencao=self._classificar(sinais, entidades, afirmativa, negativa),
            entidades=entidades,
            total_palavras=len(palavras),
            afirmativa=afirmativa,
            negativa=negativa,
            pede_outra_opcao=SINAL_OUTRA_OPCAO in sinais,
            sem_preferencia=SINAL_SEM_PREFERENCIA in sinais,
        )

    @staticmethod
    def _classificar(sinais: dict[str, list[int]], entidades: Entidades, afirmativa: bool, negativa: bool) -> Intencao:
        for intencao in INTENCOES_DE_ACAO:
            if intencao in sinais:
                return intencao
        if Intencao.ORIENTACAO_MEDICA in sinais:
            return Intencao.ORIENTACAO_MEDICA
        if entidades.especialidade or entidades.medico or SINAL_MENCAO_CONSULTA in sinais:
            return Intencao.AGENDAR
        if negativa:
            return Intencao.NEGAR
        if afirmativa:
            return Intencao.CONFIRMAR
        for intencao in INTENCOES_SOCIAIS:
            if intencao in sinais:
                return intencao
        return Intencao.DESCONHECIDA

    def _extrair_entidades(self, doc: Doc) -> Entidades:
        turno = self._primeiro_id(doc, "TURNO")
        valores: dict[str, Any] = {"turno": turno} if turno else {}
        for ent in doc.ents:
            match ent.label_:
                case "ESPECIALIDADE":
                    valores.setdefault("especialidade", ent.ent_id_)
                case "MEDICO":
                    valores.setdefault("medico", self._nome_sem_titulo(ent))
                case "DATA":
                    if data := self._resolver_data(ent):
                        valores.setdefault("data", data)
                case "DIA_SEMANA":
                    valores.setdefault("data", self._resolver.dia_da_semana(int(ent.ent_id_)))
                case "PERIODO":
                    valores.setdefault("periodo", self._resolver.periodo(ent.ent_id_))
                case "HORA":
                    if hora := self._resolver.hora(ent.text, turno):
                        valores.setdefault("hora", hora)
        if inferida := self._primeiro_id(doc, "ESPECIALIDADE_INFERIDA"):
            valores.setdefault("especialidade", inferida)
        return Entidades(**valores)

    @staticmethod
    def _primeiro_id(doc: Doc, rotulo: str) -> str | None:
        return next((ent.ent_id_ for ent in doc.ents if ent.label_ == rotulo), None)

    def _resolver_data(self, ent: Span) -> date | None:
        if ent.ent_id_ == "explicita":
            return self._resolver.data_explicita(ent.text)
        if ent.ent_id_ == "dia_do_mes":
            return self._resolver.dia_do_mes(int(ent[-1].text))
        return self._resolver.data_relativa(ent.ent_id_)

    @staticmethod
    def _nome_sem_titulo(ent: Span) -> str:
        return " ".join(token.text for token in ent if token.is_alpha and token.norm_ not in TITULOS_MEDICOS)
