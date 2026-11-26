"""Política do estilo de comunicação do assistente.

O estilo muda somente a redação e a quantidade de opções mostradas por vez. Vagas,
operações e confirmações são as mesmas para todas as pessoas. O paciente nunca escolhe
entre rótulos etários e nunca vê rótulos, probabilidades ou o diagnóstico do classificador.

Prioridade, da mais forte para a mais fraca:

1. Pedido explícito: "modo simples", "explique melhor", "vá por partes", "seja mais direto",
   "modo padrão", "modo automático" e "mostre mais horários" (este só amplia a quantidade).
2. Pedido de ajuda na própria mensagem ("não entendi", "como assim?", "pode repetir?"):
   passa ao passo a passo, inclusive para quem começou no estilo direto.
3. Apresentação inicial pela idade em anos completos calculada no backend a partir do
   cadastro: a partir do limiar configurável (60 anos) ou com data ausente/inválida, começa
   com uma pergunta por vez e até duas opções; abaixo do limiar, começa direto.
4. Evidência do classificador Random Forest sobre as heurísticas do texto. Só mensagens com
   pelo menos quatro palavras contam ("oi", "sim" e "2" não dizem nada sobre o estilo); cada
   mensagem move a evidência no máximo pela metade e a troca exige cruzar limiares distantes
   (histerese), para o estilo não alternar a cada resposta curta.

Limitações do classificador: foi treinado num corpus sintético de 118 frases rotuladas por
perfil etário; mede consistência com esse corpus, não idade real, letramento ou compreensão.
Por isso ele é apenas o último critério e nunca altera o primeiro estilo da conversa.
"""
import base64
import hashlib
from dataclasses import dataclass
from enum import StrEnum

from cryptography.fernet import Fernet, InvalidToken

from app.backend.core.text import normalizar_frase


class EstiloComunicacao(StrEnum):
    PASSO_A_PASSO = "passo_a_passo"
    DIRETO = "direto"


OPCOES_POR_VEZ = {EstiloComunicacao.PASSO_A_PASSO: 2, EstiloComunicacao.DIRETO: 6}
MAXIMO_OPCOES_POR_VEZ = max(OPCOES_POR_VEZ.values())


class PedidoDeEstilo(StrEnum):
    PASSO_A_PASSO = "passo_a_passo"
    DIRETO = "direto"
    AUTOMATICO = "automatico"
    MAIS_OPCOES = "mais_opcoes"


PREFERENCIA_DO_PEDIDO = {
    PedidoDeEstilo.PASSO_A_PASSO: "simplificado",
    PedidoDeEstilo.DIRETO: "padrao",
    PedidoDeEstilo.AUTOMATICO: "automatico",
}
ESTILO_DA_PREFERENCIA = {"simplificado": EstiloComunicacao.PASSO_A_PASSO, "padrao": EstiloComunicacao.DIRETO}

_FRASES_DE_ESTILO: dict[PedidoDeEstilo, tuple[str, ...]] = {
    # Os quatro primeiros comandos de cada grupo existiam antes desta política e continuam válidos.
    PedidoDeEstilo.PASSO_A_PASSO: (
        "fale simples", "linguagem simples", "modo simples", "modo simplificado",
        "fala simples", "mais simples", "fale mais simples", "explique melhor", "explica melhor",
        "explicar melhor", "me explica melhor", "me explique melhor", "pode explicar melhor",
        "va por partes", "vai por partes", "vamos por partes", "por partes", "passo a passo",
        "um passo de cada vez", "uma coisa de cada vez", "mais devagar", "fale mais devagar",
        "va devagar", "vai devagar", "explique com calma", "explica com calma",
    ),
    PedidoDeEstilo.DIRETO: (
        "modo padrao", "linguagem padrao", "modo direto", "seja direto", "seja mais direto", "mais direto",
        "pode ser direto", "pode ser mais direto", "va direto ao ponto", "vai direto ao ponto",
        "direto ao ponto", "resumido", "mais resumido", "seja breve", "mais rapido", "fale normal",
    ),
    PedidoDeEstilo.AUTOMATICO: ("modo automatico", "linguagem automatica"),
    PedidoDeEstilo.MAIS_OPCOES: (
        "mostre mais horarios", "mostra mais horarios", "mostrar mais horarios", "me mostre mais horarios",
        "me mostra mais horarios", "quero ver mais horarios", "ver mais horarios", "mostre mais opcoes",
        "mostra mais opcoes", "mostrar mais opcoes", "quero ver mais opcoes", "mais opcoes de uma vez",
        "mais horarios de uma vez", "mostre todos os horarios", "mostra todos os horarios",
    ),
}
_PEDIDOS = {frase: pedido for pedido, frases in _FRASES_DE_ESTILO.items() for frase in frases}


def ler_pedido_de_estilo(texto: str) -> PedidoDeEstilo | None:
    """Só a mensagem inteira vale como pedido, para não confundir "mais horários na sexta" com estilo."""
    frase = normalizar_frase(texto)
    for candidata in (frase, *(frase.removeprefix(prefixo) for prefixo in ("pode ", "por favor ", "quero que "))):
        if candidata in _PEDIDOS:
            return _PEDIDOS[candidata]
    return None


@dataclass(frozen=True)
class EstadoDeEstilo:
    preferencia: str = "automatico"
    estilo: EstiloComunicacao | None = None
    opcoes_por_vez: int | None = None
    evidencia: float | None = None


@dataclass(frozen=True)
class SinaisDaMensagem:
    pedido: PedidoDeEstilo | None = None
    pediu_ajuda: bool = False
    palavras: int = 0
    previsao_passo_a_passo: float | None = None


@dataclass(frozen=True)
class DecisaoDeEstilo:
    estilo: EstiloComunicacao
    opcoes_por_vez: int
    estado: EstadoDeEstilo


class CofreDeEvidencia:
    """Guarda a evidência do classificador no contexto sem expô-la: o valor viaja cifrado.

    A API não guarda estado entre mensagens; sem a cifra, a evidência inicial (1 ou 0)
    revelaria a faixa etária e as seguintes, a probabilidade do classificador.
    """

    def __init__(self, segredo: str):
        chave = hashlib.sha256(f"estilo-de-comunicacao:{segredo}".encode()).digest()
        self._fernet = Fernet(base64.urlsafe_b64encode(chave))

    def fechar(self, evidencia: float | None) -> str | None:
        return None if evidencia is None else self._fernet.encrypt(f"{evidencia:.4f}".encode()).decode()

    def abrir(self, estado: str | None) -> float | None:
        if not estado:
            return None
        try:
            valor = float(self._fernet.decrypt(estado.encode()))
        except (InvalidToken, ValueError):
            return None
        return valor if 0 <= valor <= 1 else None


class PoliticaDeEstilo:
    PALAVRAS_MINIMAS_PARA_EVIDENCIA = 4
    PALAVRAS_PARA_PESO_PLENO = 8
    PESO_MAXIMO_POR_MENSAGEM = 0.5
    LIMIAR_PARA_DIRETO = 0.25
    LIMIAR_PARA_PASSO_A_PASSO = 0.75

    def __init__(self, idade_limiar: int):
        self.idade_limiar = idade_limiar

    def inicial(self, idade: int | None) -> EstiloComunicacao:
        if idade is not None and idade < self.idade_limiar:
            return EstiloComunicacao.DIRETO
        return EstiloComunicacao.PASSO_A_PASSO

    def decidir(self, anterior: EstadoDeEstilo, idade: int | None, sinais: SinaisDaMensagem) -> DecisaoDeEstilo:
        preferencia, opcoes = anterior.preferencia, anterior.opcoes_por_vez
        if sinais.pedido in PREFERENCIA_DO_PEDIDO:
            preferencia, opcoes = PREFERENCIA_DO_PEDIDO[sinais.pedido], None
        elif sinais.pedido == PedidoDeEstilo.MAIS_OPCOES:
            opcoes = MAXIMO_OPCOES_POR_VEZ

        automatico = anterior.estilo or self.inicial(idade)
        evidencia = anterior.evidencia
        if evidencia is None:
            evidencia = 1.0 if automatico == EstiloComunicacao.PASSO_A_PASSO else 0.0
        if sinais.pediu_ajuda:
            automatico, evidencia = EstiloComunicacao.PASSO_A_PASSO, 1.0
        elif self._conta_como_evidencia(sinais):
            peso = self.PESO_MAXIMO_POR_MENSAGEM * min(1.0, sinais.palavras / self.PALAVRAS_PARA_PESO_PLENO)
            evidencia = round((1 - peso) * evidencia + peso * sinais.previsao_passo_a_passo, 4)
            if anterior.estilo is not None:
                automatico = self._com_histerese(automatico, evidencia)

        estilo = ESTILO_DA_PREFERENCIA.get(preferencia, automatico)
        estado = EstadoDeEstilo(preferencia, estilo, opcoes, evidencia)
        return DecisaoDeEstilo(estilo, opcoes or OPCOES_POR_VEZ[estilo], estado)

    def _conta_como_evidencia(self, sinais: SinaisDaMensagem) -> bool:
        return sinais.previsao_passo_a_passo is not None and sinais.palavras >= self.PALAVRAS_MINIMAS_PARA_EVIDENCIA

    def _com_histerese(self, atual: EstiloComunicacao, evidencia: float) -> EstiloComunicacao:
        if atual == EstiloComunicacao.PASSO_A_PASSO and evidencia <= self.LIMIAR_PARA_DIRETO:
            return EstiloComunicacao.DIRETO
        if atual == EstiloComunicacao.DIRETO and evidencia >= self.LIMIAR_PARA_PASSO_A_PASSO:
            return EstiloComunicacao.PASSO_A_PASSO
        return atual
