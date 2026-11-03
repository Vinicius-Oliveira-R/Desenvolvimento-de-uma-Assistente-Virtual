import csv
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path

from sklearn.ensemble import RandomForestClassifier
from spacy.tokens import Doc

from app.backend.ml.heuristics import HeuristicVector, NielsenHeuristicExtractor

CORPUS_PADRAO = Path(__file__).resolve().parent / "data" / "corpus_perfil.csv"


class PerfilEtario(StrEnum):
    IDOSO = "IDOSO"
    PADRAO = "PADRAO"


@dataclass(frozen=True)
class ProfilePrediction:
    perfil: PerfilEtario
    probabilidade_idoso: float


class AgeProfileClassifier:
    LIMIAR_IDOSO = 0.5

    def __init__(self, modelo: RandomForestClassifier):
        self._modelo = modelo
        self._indice_idoso = list(modelo.classes_).index(PerfilEtario.IDOSO)

    @staticmethod
    def build_model(random_state: int = 42) -> RandomForestClassifier:
        return RandomForestClassifier(
            n_estimators=200,
            min_samples_leaf=2,
            class_weight="balanced",
            random_state=random_state,
        )

    @classmethod
    def train(cls, vetores: Sequence[HeuristicVector], perfis: Sequence[PerfilEtario]) -> "AgeProfileClassifier":
        modelo = cls.build_model()
        modelo.fit([vetor.as_list() for vetor in vetores], [str(perfil) for perfil in perfis])
        return cls(modelo)

    def predict(self, vetor: HeuristicVector) -> ProfilePrediction:
        probabilidade = float(self._modelo.predict_proba([vetor.as_list()])[0][self._indice_idoso])
        perfil = PerfilEtario.IDOSO if probabilidade >= self.LIMIAR_IDOSO else PerfilEtario.PADRAO
        return ProfilePrediction(perfil, round(probabilidade, 4))

    def feature_importances(self) -> dict[str, float]:
        return {
            nome: round(float(importancia), 4)
            for nome, importancia in zip(HeuristicVector.feature_names(), self._modelo.feature_importances_)
        }


def load_corpus(caminho: Path = CORPUS_PADRAO) -> list[tuple[str, PerfilEtario]]:
    with caminho.open(encoding="utf-8", newline="") as arquivo:
        return [(linha["texto"], PerfilEtario(linha["perfil"])) for linha in csv.DictReader(arquivo)]


def vectorize_corpus(
    corpus: Sequence[tuple[str, PerfilEtario]],
    processar: Callable[[str], Doc],
    extrator: NielsenHeuristicExtractor,
) -> tuple[list[HeuristicVector], list[PerfilEtario]]:
    vetores = [extrator.extract(processar(texto)) for texto, _ in corpus]
    return vetores, [perfil for _, perfil in corpus]


def train_from_corpus(
    processar: Callable[[str], Doc],
    extrator: NielsenHeuristicExtractor,
    caminho: Path = CORPUS_PADRAO,
) -> AgeProfileClassifier:
    vetores, perfis = vectorize_corpus(load_corpus(caminho), processar, extrator)
    return AgeProfileClassifier.train(vetores, perfis)
