import pytest
from sklearn.model_selection import StratifiedKFold, cross_val_score

from app.backend.assistant.nlp import get_language_processor
from app.backend.ml.heuristics import HeuristicVector, NielsenHeuristicExtractor
from app.backend.ml.profile_classifier import (
    AgeProfileClassifier,
    PerfilEtario,
    load_corpus,
    train_from_corpus,
    vectorize_corpus,
)

MENSAGEM_IDOSO = "queria marca consulta com cardiologista pra semana q vem se der..."
MENSAGEM_PADRAO = "Quero agendar consulta com Dra. Maria dia 25/10 às 14h"


def _vetor(texto: str) -> HeuristicVector:
    return NielsenHeuristicExtractor().extract(get_language_processor().process(texto))


def test_vetor_de_heuristicas_mede_erros_hesitacao_e_vagueza() -> None:
    idoso, padrao = _vetor(MENSAGEM_IDOSO), _vetor(MENSAGEM_PADRAO)

    assert idoso.taxa_erros == pytest.approx(2 / 11, abs=1e-3)
    assert idoso.hesitacao == pytest.approx(3 / 11, abs=1e-3)
    assert idoso.vagueza == 1.0
    assert idoso.informalidade > 0.5
    assert padrao == HeuristicVector(0.0, padrao.complexidade, 0.0, 0.0, 0.0)
    assert 0.0 <= idoso.complexidade <= 1.0


def test_complexidade_cresce_com_frases_longas_e_palavras_polissilabicas() -> None:
    simples = _vetor("Quero marcar consulta.")
    complexa = _vetor(
        "Gostaria de verificar a disponibilidade de agendamento de uma consulta oftalmológica "
        "considerando minha impossibilidade de comparecimento matutino"
    )

    assert complexa.complexidade > simples.complexidade


def test_random_forest_classifica_perfis_dos_cenarios_fora_do_corpus() -> None:
    corpus = {texto for texto, _ in load_corpus()}
    assert MENSAGEM_IDOSO not in corpus and MENSAGEM_PADRAO not in corpus

    classificador = train_from_corpus(get_language_processor().process, NielsenHeuristicExtractor())

    assert classificador.predict(_vetor(MENSAGEM_IDOSO)).perfil == PerfilEtario.IDOSO
    assert classificador.predict(_vetor(MENSAGEM_PADRAO)).perfil == PerfilEtario.PADRAO


def test_random_forest_generaliza_em_validacao_cruzada() -> None:
    vetores, perfis = vectorize_corpus(load_corpus(), get_language_processor().process, NielsenHeuristicExtractor())
    acuracias = cross_val_score(
        AgeProfileClassifier.build_model(),
        [vetor.as_list() for vetor in vetores],
        [str(perfil) for perfil in perfis],
        cv=StratifiedKFold(n_splits=5, shuffle=True, random_state=42),
    )

    assert acuracias.mean() >= 0.8
