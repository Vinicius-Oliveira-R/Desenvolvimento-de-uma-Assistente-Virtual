"""Orquestra interpretação, estilo, diálogo e resposta do chat do paciente.

A idade é calculada aqui, a partir do cadastro, e nunca sai do backend. A resposta não
contém rótulo etário, probabilidade nem heurísticas: só o estilo neutro usado na redação.
Cada pergunta que espera resposta recebe uma proposta nova; um botão só vale para a
proposta que o criou.
"""
import secrets
from dataclasses import replace
from functools import lru_cache

from sqlalchemy.orm import Session

from app.backend.assistant.communication_style import (
    MAXIMO_OPCOES_POR_VEZ,
    CofreDeEvidencia,
    DecisaoDeEstilo,
    EstadoDeEstilo,
    EstiloComunicacao,
    PedidoDeEstilo,
    PoliticaDeEstilo,
    SinaisDaMensagem,
    ler_pedido_de_estilo,
)
from app.backend.assistant.dialogue import APRESENTACOES_DE_SOLICITACAO, Preambulo, ResultadoDialogo, TipoResultado
from app.backend.assistant.nlp import LanguageProcessor, MensagemInterpretada, get_language_processor
from app.backend.assistant.replies import pede_explicacao
from app.backend.assistant.responses import ResponseDecisionTree
from app.backend.assistant.scheduling_flow import SchedulingDialogueManager, SchedulingMessageInterpreter
from app.backend.assistant.temporal import TemporalResolver
from app.backend.core.clock import Clock
from app.backend.core.config import get_settings
from app.backend.core.idade import idade_do_cadastro
from app.backend.ml.heuristics import NielsenHeuristicExtractor
from app.backend.ml.profile_classifier import AgeProfileClassifier, train_from_corpus
from app.backend.ml.resilience import predictor
from app.backend.models import Paciente
from app.backend.repositories.paciente_repository import PacienteRepository
from app.backend.schemas.assistant import AcaoPendente, ChatRequest, ChatResponse, ContextoConversa

PREAMBULO_DO_PEDIDO = {
    PedidoDeEstilo.PASSO_A_PASSO: Preambulo.ESTILO_PASSO_A_PASSO,
    PedidoDeEstilo.DIRETO: Preambulo.ESTILO_DIRETO,
    PedidoDeEstilo.AUTOMATICO: Preambulo.ESTILO_AUTOMATICO,
    PedidoDeEstilo.MAIS_OPCOES: Preambulo.MAIS_OPCOES,
}


@lru_cache
def get_profile_classifier() -> AgeProfileClassifier:
    return train_from_corpus(get_language_processor().process, NielsenHeuristicExtractor())


class ChatOrchestrator:
    def __init__(
        self,
        db: Session,
        clock: Clock,
        processor: LanguageProcessor,
        classifier: AgeProfileClassifier | None,
        extractor: NielsenHeuristicExtractor | None = None,
        decision_tree: ResponseDecisionTree | None = None,
        politica: PoliticaDeEstilo | None = None,
    ):
        self.clock = clock
        self.interpreter = SchedulingMessageInterpreter(processor, TemporalResolver(clock))
        self.extractor = extractor or NielsenHeuristicExtractor()
        self.classifier = classifier
        self.decision_tree = decision_tree or ResponseDecisionTree()
        self.dialogue = SchedulingDialogueManager(db, clock)
        self.pacientes = PacienteRepository(db)
        settings = get_settings()
        self.politica = politica or PoliticaDeEstilo(settings.assistente_idade_passo_a_passo)
        self.cofre = CofreDeEvidencia(settings.secret_key)

    @classmethod
    def build(cls, db: Session, clock: Clock) -> "ChatOrchestrator":
        return cls(db, clock, get_language_processor(), None)

    def reply(self, usuario_id: int, requisicao: ChatRequest) -> ChatResponse:
        contexto = requisicao.contexto
        paciente = self.pacientes.get_by_usuario_id(usuario_id)
        idade = self._idade(paciente)
        mensagem = self.interpreter.interpret(requisicao.mensagem)
        botao = requisicao.acao
        pedido = None if botao else self._pedido_de_estilo(requisicao.mensagem, contexto, idade)
        previsao, degradado = self._prever(mensagem, botao is not None)
        sinais = SinaisDaMensagem(
            pedido=pedido,
            pediu_ajuda=botao is None and pede_explicacao(requisicao.mensagem),
            palavras=mensagem.total_palavras,
            previsao_passo_a_passo=previsao,
        )
        decisao = self._decidir(contexto, idade, sinais)
        if paciente is None:
            resultado = ResultadoDialogo(TipoResultado.PACIENTE_NAO_CADASTRADO)
        elif pedido is not None:
            resultado = self.dialogue.mudar_apresentacao(paciente, contexto.acao_pendente, PREAMBULO_DO_PEDIDO[pedido])
        else:
            resultado = self.dialogue.handle(
                mensagem, paciente, contexto.acao_pendente, contexto.solicitacoes_vistas, botao
            )
        return self._responder(resultado, decisao, contexto, mensagem, degradado)

    def retomar(self, usuario_id: int, contexto: ContextoConversa) -> ChatResponse:
        """Ao abrir ou atualizar o chat: reapresenta a etapa pendente, revalidada, ou a abertura."""
        paciente = self.pacientes.get_by_usuario_id(usuario_id)
        decisao = self._decidir(contexto, self._idade(paciente), SinaisDaMensagem())
        if paciente is None:
            resultado = ResultadoDialogo(TipoResultado.PACIENTE_NAO_CADASTRADO)
        else:
            resultado = self.dialogue.retomar(paciente, contexto.acao_pendente, contexto.solicitacoes_vistas)
        return self._responder(resultado, decisao, contexto, None, False)

    def _decidir(self, contexto: ContextoConversa, idade: int | None, sinais: SinaisDaMensagem) -> DecisaoDeEstilo:
        anterior = EstadoDeEstilo(
            preferencia=contexto.preferencia_estilo,
            estilo=EstiloComunicacao(contexto.estilo) if contexto.estilo else None,
            opcoes_por_vez=contexto.opcoes_por_vez,
            evidencia=self.cofre.abrir(contexto.estado_estilo),
        )
        decisao = self.politica.decidir(anterior, idade, sinais)
        self.dialogue.page_size = decisao.opcoes_por_vez
        return decisao

    def _pedido_de_estilo(self, texto: str, contexto: ContextoConversa, idade: int | None) -> PedidoDeEstilo | None:
        pedido = ler_pedido_de_estilo(texto)
        if pedido == PedidoDeEstilo.MAIS_OPCOES:
            atual = self._decidir(contexto, idade, SinaisDaMensagem())
            # Quem já vê o máximo de opções por vez recebe a próxima página, como em "mais horários".
            return None if atual.opcoes_por_vez >= MAXIMO_OPCOES_POR_VEZ else pedido
        return pedido

    def _prever(self, mensagem: MensagemInterpretada, por_botao: bool) -> tuple[float | None, bool]:
        """O rótulo IDOSO do corpus é lido apenas como evidência a favor do passo a passo."""
        if por_botao or mensagem.total_palavras < PoliticaDeEstilo.PALAVRAS_MINIMAS_PARA_EVIDENCIA:
            return None, False
        vetor = self.extractor.extract(mensagem.doc)
        settings = get_settings()
        previsao = predictor.call(
            lambda: (self.classifier or get_profile_classifier()).predict(vetor),
            timeout=settings.ml_timeout_seconds, retry_seconds=settings.ml_retry_seconds,
        )
        return (None, True) if previsao is None else (previsao.probabilidade_idoso, False)

    def _idade(self, paciente: Paciente | None) -> int | None:
        return idade_do_cadastro(paciente.data_nascimento, self.clock.today()) if paciente else None

    def _responder(
        self,
        resultado: ResultadoDialogo,
        decisao: DecisaoDeEstilo,
        contexto: ContextoConversa,
        mensagem: MensagemInterpretada | None,
        degradado: bool,
    ) -> ChatResponse:
        resultado = replace(resultado, acao_pendente=self._com_proposta(resultado.acao_pendente, contexto.acao_pendente))
        composta = self.decision_tree.respond(decisao.estilo, resultado)
        estado = decisao.estado
        return ChatResponse(
            resposta=composta.texto,
            opcoes=composta.opcoes,
            estilo=decisao.estilo,
            intencao=mensagem.intencao if mensagem else "retomada",
            resultado=resultado.tipo,
            entidades=mensagem.entidades.as_dict() if mensagem else {},
            modo_degradado=degradado,
            contexto=ContextoConversa(
                preferencia_estilo=estado.preferencia,
                estilo=estado.estilo,
                opcoes_por_vez=estado.opcoes_por_vez,
                estado_estilo=self.cofre.fechar(estado.evidencia),
                acao_pendente=resultado.acao_pendente,
                solicitacoes_vistas=self._vistas(contexto.solicitacoes_vistas, resultado),
            ),
            consulta=resultado.consulta,
        )

    @staticmethod
    def _com_proposta(nova: AcaoPendente | None, anterior: AcaoPendente | None) -> AcaoPendente | None:
        """A mesma pergunta reapresentada mantém a proposta; qualquer mudança gera outra."""
        if nova is None:
            return None
        if anterior is not None and anterior.proposta and nova.sem_proposta() == anterior.sem_proposta():
            return nova.model_copy(update={"proposta": anterior.proposta})
        return nova.model_copy(update={"proposta": secrets.token_urlsafe(9)})

    @staticmethod
    def _vistas(anteriores: list[int], resultado: ResultadoDialogo) -> list[int]:
        if resultado.tipo in APRESENTACOES_DE_SOLICITACAO and resultado.acao_pendente:
            return list(dict.fromkeys([*anteriores, resultado.acao_pendente.notificacao_id]))[-120:]
        return anteriores
