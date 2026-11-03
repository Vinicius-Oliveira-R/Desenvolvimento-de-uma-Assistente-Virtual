from dataclasses import asdict
from functools import lru_cache

from sqlalchemy.orm import Session

from app.backend.assistant.dialogue import DialogueManager, ResultadoDialogo, TipoResultado
from app.backend.assistant.nlp import LanguageProcessor, MessageInterpreter, get_language_processor
from app.backend.assistant.responses import ResponseDecisionTree
from app.backend.assistant.temporal import TemporalResolver
from app.backend.core.clock import Clock
from app.backend.ml.heuristics import NielsenHeuristicExtractor
from app.backend.ml.profile_classifier import AgeProfileClassifier, PerfilEtario, train_from_corpus
from app.backend.repositories.paciente_repository import PacienteRepository
from app.backend.schemas.assistant import ChatRequest, ChatResponse, ContextoConversa, HeuristicasOut


@lru_cache
def get_profile_classifier() -> AgeProfileClassifier:
    return train_from_corpus(get_language_processor().process, NielsenHeuristicExtractor())


class ChatOrchestrator:
    PALAVRAS_PARA_EVIDENCIA_PLENA = 8

    def __init__(
        self,
        db: Session,
        clock: Clock,
        processor: LanguageProcessor,
        classifier: AgeProfileClassifier,
        extractor: NielsenHeuristicExtractor | None = None,
        decision_tree: ResponseDecisionTree | None = None,
    ):
        self.interpreter = MessageInterpreter(processor, TemporalResolver(clock))
        self.extractor = extractor or NielsenHeuristicExtractor()
        self.classifier = classifier
        self.decision_tree = decision_tree or ResponseDecisionTree()
        self.dialogue = DialogueManager(db, clock)
        self.pacientes = PacienteRepository(db)

    @classmethod
    def build(cls, db: Session, clock: Clock) -> "ChatOrchestrator":
        return cls(db, clock, get_language_processor(), get_profile_classifier())

    def reply(self, usuario_id: int, requisicao: ChatRequest) -> ChatResponse:
        mensagem = self.interpreter.interpret(requisicao.mensagem)
        vetor = self.extractor.extract(mensagem.doc)
        probabilidade = self._suavizar(
            self.classifier.predict(vetor).probabilidade_idoso,
            requisicao.contexto.probabilidade_idoso,
            mensagem.total_palavras,
        )
        perfil = PerfilEtario.IDOSO if probabilidade >= AgeProfileClassifier.LIMIAR_IDOSO else PerfilEtario.PADRAO

        paciente = self.pacientes.get_by_usuario_id(usuario_id)
        resultado = (
            self.dialogue.handle(mensagem, paciente, requisicao.contexto.acao_pendente)
            if paciente
            else ResultadoDialogo(TipoResultado.PACIENTE_NAO_CADASTRADO)
        )
        return ChatResponse(
            resposta=self.decision_tree.respond(perfil, resultado),
            perfil=perfil,
            probabilidade_idoso=probabilidade,
            intencao=mensagem.intencao,
            resultado=resultado.tipo,
            entidades=mensagem.entidades.as_dict(),
            heuristicas=HeuristicasOut(**asdict(vetor)),
            contexto=ContextoConversa(acao_pendente=resultado.acao_pendente, probabilidade_idoso=probabilidade),
            consulta=resultado.consulta,
        )

    def _suavizar(self, atual: float, anterior: float | None, palavras: int) -> float:
        if anterior is None:
            return atual
        peso = min(1.0, palavras / self.PALAVRAS_PARA_EVIDENCIA_PLENA)
        return round(peso * atual + (1 - peso) * anterior, 4)
