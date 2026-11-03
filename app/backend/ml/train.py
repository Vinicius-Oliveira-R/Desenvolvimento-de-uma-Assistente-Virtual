"""Avalia o classificador de perfil etário com validação cruzada estratificada (5 folds).

Uso: python -m app.backend.ml.train
"""

from sklearn.metrics import classification_report, confusion_matrix
from sklearn.model_selection import StratifiedKFold, cross_val_predict

from app.backend.assistant.nlp import get_language_processor
from app.backend.ml.heuristics import NielsenHeuristicExtractor
from app.backend.ml.profile_classifier import AgeProfileClassifier, PerfilEtario, load_corpus, vectorize_corpus


def main() -> None:
    vetores, perfis = vectorize_corpus(load_corpus(), get_language_processor().process, NielsenHeuristicExtractor())
    amostras = [vetor.as_list() for vetor in vetores]
    rotulos = [str(perfil) for perfil in perfis]
    validacao = StratifiedKFold(n_splits=5, shuffle=True, random_state=42)
    predicoes = cross_val_predict(AgeProfileClassifier.build_model(), amostras, rotulos, cv=validacao)

    classes = [str(PerfilEtario.IDOSO), str(PerfilEtario.PADRAO)]
    print(f"Corpus: {len(rotulos)} exemplos ({rotulos.count(classes[0])} IDOSO / {rotulos.count(classes[1])} PADRAO)\n")
    print(classification_report(rotulos, predicoes, labels=classes, digits=3))
    print("Matriz de confusão (linhas = real, colunas = previsto):", classes)
    print(confusion_matrix(rotulos, predicoes, labels=classes), "\n")

    print("Importância das heurísticas no Random Forest:")
    importancias = AgeProfileClassifier.train(vetores, perfis).feature_importances()
    for nome, valor in sorted(importancias.items(), key=lambda item: item[1], reverse=True):
        print(f"  {nome:<14} {valor:.3f}")


if __name__ == "__main__":
    main()
