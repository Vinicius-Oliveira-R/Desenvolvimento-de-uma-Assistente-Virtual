"""Avaliação reprodutível: python -m app.backend.ml.train --output evidence/ml.json."""
import argparse
import hashlib
import importlib.metadata
import json
import platform
import subprocess
from collections import Counter
from pathlib import Path

import numpy as np
from sklearn.metrics import accuracy_score, classification_report, confusion_matrix, f1_score
from sklearn.model_selection import StratifiedKFold, cross_validate, cross_val_predict

from app.backend.assistant.nlp import get_language_processor
from app.backend.ml.heuristics import NielsenHeuristicExtractor, HeuristicVector
from app.backend.ml.profile_classifier import AgeProfileClassifier, CORPUS_PADRAO, PerfilEtario, load_corpus, vectorize_corpus

F1_MINIMUM = 0.80


def evaluate() -> dict:
    corpus = load_corpus()
    vectors, profiles = vectorize_corpus(corpus, get_language_processor().process, NielsenHeuristicExtractor())
    samples = [vector.as_list() for vector in vectors]
    labels = [str(profile) for profile in profiles]
    cv = StratifiedKFold(n_splits=5, shuffle=True, random_state=42)
    model = AgeProfileClassifier.build_model()
    predictions = cross_val_predict(model, samples, labels, cv=cv)
    scores = cross_validate(model, samples, labels, cv=cv, scoring={"f1_macro": "f1_macro", "accuracy": "accuracy"})
    classes = [str(PerfilEtario.IDOSO), str(PerfilEtario.PADRAO)]
    try:
        commit = subprocess.check_output(["git", "rev-parse", "HEAD"], text=True, stderr=subprocess.DEVNULL).strip()
    except (OSError, subprocess.CalledProcessError):
        commit = None
    report = {
        "commit": commit, "python": platform.python_version(),
        "versions": {name: importlib.metadata.version(name) for name in ("scikit-learn", "spacy", "numpy")},
        "corpus_sha256": hashlib.sha256(CORPUS_PADRAO.read_bytes()).hexdigest(),
        "corpus_size": len(corpus), "class_counts": dict(Counter(labels)),
        "features": list(HeuristicVector.feature_names()),
        "model_params": model.get_params(),
        "validation": {"type": "StratifiedKFold", "n_splits": 5, "shuffle": True, "random_state": 42},
        "accuracy": accuracy_score(labels, predictions),
        "f1_macro": f1_score(labels, predictions, average="macro"),
        "classification_report": classification_report(labels, predictions, labels=classes, output_dict=True, zero_division=0),
        "confusion_matrix": {"labels": classes, "rows_actual_columns_predicted": confusion_matrix(labels, predictions, labels=classes).tolist()},
        "folds": {key: value.tolist() for key, value in scores.items()},
        "predictions": [{"row": i + 2, "actual": real, "predicted": str(predicted)} for i, (real, predicted) in enumerate(zip(labels, predictions))],
        "acceptance": {"metric": "mean_fold_f1_macro", "threshold": F1_MINIMUM,
                       "value": float(np.mean(scores["test_f1_macro"])),
                       "passed": bool(np.mean(scores["test_f1_macro"]) >= F1_MINIMUM)},
        "limitations": "Corpus sintético; não demonstra idade real, compreensão ou benefício clínico; sem validação externa",
    }
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    report = evaluate()
    print(json.dumps(report, ensure_ascii=False, indent=2, allow_nan=False))
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2, allow_nan=False), encoding="utf-8")
    if not report["acceptance"]["passed"]:
        raise SystemExit("F1 macro médio abaixo do critério de aceite")


if __name__ == "__main__":
    main()
