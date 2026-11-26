"""Árvore de decisão determinística da resposta adaptativa.

Nível 1 - estilo de comunicação decidido pela PoliticaDeEstilo: passo a passo ou direto.
Nível 2 - resultado do diálogo (TipoResultado) -> modelo de mensagem do estilo escolhido.
Nível 3 - dados opcionais (avisos, preâmbulo, consulta atual, opções) completam texto e botões.

Os dois estilos comunicam o mesmo conteúdo: o que está sendo oferecido, o que ainda depende de
confirmação e o que já foi registrado. Muda a redação e quantas opções aparecem de cada vez.
O passo a passo usa frases curtas com uma ideia, termos leigos, datas por extenso e no máximo
uma instrução; cabeçalhos terminados em ":" introduzem a etapa e não contam como unidade.
"""

from abc import ABC
from collections import Counter
from collections.abc import Sequence
from dataclasses import dataclass, field, replace
from datetime import date
from typing import ClassVar

from app.backend.assistant.communication_style import EstiloComunicacao
from app.backend.assistant.dialogue import Aviso, OpcaoAgenda, Preambulo, ResultadoDialogo, TipoResultado
from app.backend.assistant.especialidades import termo_leigo
from app.backend.assistant.temporal import IntervaloDatas
from app.backend.schemas.assistant import AcaoPendente, OpcaoDeResposta, Pergunta, TipoAcao

DIAS_DA_SEMANA = ("segunda-feira", "terça-feira", "quarta-feira", "quinta-feira", "sexta-feira", "sábado", "domingo")
DIAS_CURTOS = ("segunda", "terça", "quarta", "quinta", "sexta", "sábado", "domingo")
MESES = (
    "janeiro", "fevereiro", "março", "abril", "maio", "junho",
    "julho", "agosto", "setembro", "outubro", "novembro", "dezembro",
)
_NUMEROS = {1: "um", 2: "dois", 3: "três", 4: "quatro", 5: "cinco", 6: "seis"}
_NUMEROS_FEMININOS = {1: "uma", 2: "duas"}
_TURNOS = {"manha": "de manhã", "tarde": "à tarde", "noite": "à noite"}
_ORDEM_DOS_AVISOS = (
    Aviso.ESPECIALIDADE_PADRAO, Aviso.HORARIO_RESERVADO, Aviso.OPCOES_REDUZIDAS,
    Aviso.HORARIO_PEDIDO_INDISPONIVEL, Aviso.FORA_DO_PERIODO, Aviso.ESCOLHA_AUTOMATICA,
)


def hora_curta(hora: str) -> str:
    horas, minutos = (int(parte) for parte in hora.split(":"))
    return f"{horas}h{minutos:02d}" if minutos else f"{horas}h"


def quantidade(total: int, singular: str, plural: str, feminino: bool = False) -> str:
    numero = (_NUMEROS_FEMININOS.get(total) if feminino else None) or _NUMEROS.get(total, str(total))
    return f"{numero} {singular if total == 1 else plural}"


def rotulo_completo(opcao: OpcaoAgenda) -> str:
    return f"{DIAS_CURTOS[opcao.data.weekday()].capitalize()}, {opcao.data:%d/%m}, às {hora_curta(opcao.hora)}"


def rotulos_curtos(opcoes: Sequence[OpcaoAgenda]) -> list[str]:
    """Rótulos de botão com o dado que distingue as opções: hora, depois data, depois médico."""
    mesma_data = len({opcao.data for opcao in opcoes}) == 1
    rotulos = [f"Às {hora_curta(opcao.hora)}" if mesma_data else rotulo_completo(opcao) for opcao in opcoes]
    repetidos = Counter(rotulos)
    return [f"{rotulo} — {opcao.medico}" if repetidos[rotulo] > 1 else rotulo for rotulo, opcao in zip(rotulos, opcoes)]


def referencias_distintivas(opcoes: Sequence[OpcaoAgenda]) -> list[str]:
    """ "o das 9h" / "o de terça, 10/11" / "o com Dra. Maria": a menor diferença entre as opções."""
    horas = [hora_curta(opcao.hora) for opcao in opcoes]
    if len(set(horas)) == len(horas):
        return [f"o {'da' if hora.startswith('1h') else 'das'} {hora}" for hora in horas]
    datas = [f"{DIAS_CURTOS[opcao.data.weekday()]}, {opcao.data:%d/%m}" for opcao in opcoes]
    if len(set(datas)) == len(datas):
        return [f"o de {data}" for data in datas]
    return [f"o de {data} com {opcao.medico}" for data, opcao in zip(datas, opcoes)]


def _juntar(itens: Sequence[str], conector: str = "ou") -> str:
    return itens[0] if len(itens) == 1 else f"{', '.join(itens[:-1])} {conector} {itens[-1]}"


def _tipo_de_fluxo(acao: AcaoPendente | None) -> str | None:
    if acao is None:
        return None
    if acao.tipo == TipoAcao.RESPONDER_SOLICITACAO:
        return "solicitacao"
    if acao.tipo == TipoAcao.REMARCAR:
        return "remarcar"
    if acao.tipo in (TipoAcao.CANCELAR, TipoAcao.GERENCIAR):
        return "cancelar"
    return "agendar_lista" if acao.pergunta == Pergunta.ESCOLHER_HORARIO else "agendar"


@dataclass(frozen=True)
class RespostaComposta:
    texto: str
    opcoes: list[OpcaoDeResposta] = field(default_factory=list)


class ResponseStyle(ABC):
    nome: ClassVar[str]
    modelos: ClassVar[dict[TipoResultado, str]]
    ja_registrados: ClassVar[dict[TipoResultado, str]]
    avisos: ClassVar[dict[Aviso, str]]
    preambulos: ClassVar[dict[Preambulo, str]]
    garantias: ClassVar[dict[str, str]]
    situacoes: ClassVar[dict[str, str]]
    frases: ClassVar[dict[str, str]]

    def write(self, resultado: ResultadoDialogo) -> str:
        partes = (self._preambulo(resultado).strip(), self._corpo(resultado).strip())
        return "\n".join(parte for parte in partes if parte)

    # --------------------------------------------------------- descrições
    def describe_when(self, opcao: OpcaoAgenda) -> str:
        raise NotImplementedError

    def describe_specialty(self, especialidade: str | None) -> str:
        raise NotImplementedError

    def describe_period(self, periodo: IntervaloDatas | None) -> str:
        raise NotImplementedError

    def describe_hour(self, hora: str) -> str:
        raise NotImplementedError

    def item(self, posicao: int, opcao: OpcaoAgenda) -> str:
        return self.frases["item"].format(n=posicao, quando=self.describe_when(opcao), medico=opcao.medico)

    def item_de_consulta(self, posicao: int, opcao: OpcaoAgenda) -> str:
        return self.item(posicao, opcao)

    def describe_doctors(self, medicos: Sequence[str]) -> str:
        return ", ".join(medicos)

    def _pedido(self, resultado: ResultadoDialogo) -> str:
        pedido = resultado.pedido
        if resultado.periodo:
            return self.describe_period(resultado.periodo)
        if pedido and pedido.turno:
            return _TURNOS.get(pedido.turno, "no período pedido")
        return "no período pedido"

    # --------------------------------------------------------- partes comuns
    def _preambulo(self, resultado: ResultadoDialogo) -> str:
        preambulo = resultado.preambulo
        if preambulo is None or preambulo in (
            Preambulo.OPCAO_INEXISTENTE, Preambulo.ESCOLHA_PENDENTE, Preambulo.JA_REGISTRADA
        ):
            return ""
        if preambulo == Preambulo.LIMITE_MEDICO and resultado.tipo == TipoResultado.ORIENTACAO_MEDICA_BLOQUEADA:
            return ""
        fluxo = _tipo_de_fluxo(resultado.acao_pendente)
        if preambulo == Preambulo.SITUACAO:
            return self.situacoes.get(fluxo or "", self.situacoes["nenhum"])
        garantia = self.garantias.get((fluxo or "").removesuffix("_lista"), self.garantias["nenhum"])
        if preambulo == Preambulo.RETOMADA and resultado.acao_pendente is None:
            return ""
        return self.preambulos[preambulo].format(garantia=garantia)

    def _avisos(self, resultado: ResultadoDialogo, lista: bool) -> str:
        frases = []
        for aviso in _ORDEM_DOS_AVISOS:
            if aviso not in resultado.avisos:
                continue
            if aviso == Aviso.FORA_DO_PERIODO:
                modelo = self.frases["fora_lista" if lista else "fora_unica"]
            else:
                modelo = self.avisos[aviso]
            hora = self.describe_hour(resultado.pedido.hora) if resultado.pedido and resultado.pedido.hora else ""
            frases.append(modelo.format(periodo=self._pedido(resultado), hora=hora))
        return " ".join(frases)

    def _campos(self, resultado: ResultadoDialogo) -> dict[str, str]:
        opcao, nova, atual = resultado.opcao, resultado.opcao_nova, resultado.consulta_atual
        especialidade = resultado.especialidade or (opcao.especialidade if opcao else None)
        return {
            "medico": opcao.medico if opcao else "",
            "quando": self.describe_when(opcao) if opcao else "",
            "especialidade": self.describe_specialty(especialidade),
            "especialidade_nome": especialidade or "",
            "com_especialidade": self._com_especialidade(especialidade),
            "medicos": self.describe_doctors(resultado.medicos),
            "periodo": self.describe_period(resultado.periodo),
            "detalhe": resultado.detalhe or "",
            "solicitante": resultado.detalhe or "A clínica",
            "quando_novo": self.describe_when(nova) if nova else "",
            "medico_novo": nova.medico if nova else "",
            "quando_atual": self.describe_when(atual) if atual else "",
            "medico_atual": atual.medico if atual else "",
        }

    def _com_especialidade(self, especialidade: str | None) -> str:
        return f"em {especialidade}" if especialidade else ""

    # --------------------------------------------------------- corpo por resultado
    def _corpo(self, resultado: ResultadoDialogo) -> str:
        if resultado.preambulo == Preambulo.OPCAO_INEXISTENTE:
            return self._opcao_inexistente(resultado)
        match resultado.tipo:
            case TipoResultado.SUGESTAO_HORARIO:
                return self._sugestao(resultado)
            case TipoResultado.ESCLARECER_OPCAO:
                return self._esclarecimento(resultado)
            case TipoResultado.ORIENTAR_REMARCACAO if resultado.opcoes:
                return self._lista_de_consultas(resultado, "cabecalho_origem", "instrucao_consulta")
            case TipoResultado.CANCELAMENTO_AMBIGUO:
                return self._lista_de_consultas(resultado, "cabecalho_desmarcar", "instrucao_consulta")
            case TipoResultado.GERENCIAR_CONSULTAS:
                return self._lista_de_consultas(resultado, "cabecalho_gerenciar", "instrucao_consulta")
            case TipoResultado.LISTA_CONSULTAS:
                return self._lista_de_consultas(resultado, "cabecalho_lista_consultas", "instrucao_lista_consultas")
            case TipoResultado.SEM_HORARIOS:
                return self._sem_horarios(resultado)
            case TipoResultado.SEM_PROFISSIONAL if resultado.acao_pendente is None:
                return self.frases["sem_profissional_final"].format(**self._campos(resultado))
            case TipoResultado.SAUDACAO if resultado.preambulo:
                return self.frases["pergunta_inicial"]
            case TipoResultado.CANCELAMENTO_DESCARTADO if resultado.opcao:
                return self.frases["consulta_mantida"].format(**self._campos(resultado))
            case TipoResultado.REMARCACAO_ACEITA if resultado.consulta_atual and resultado.preambulo is None:
                return self.frases["troca_registrada"].format(**self._campos(resultado))
        modelos = self.ja_registrados if resultado.preambulo == Preambulo.JA_REGISTRADA else self.modelos
        modelo = modelos.get(resultado.tipo, self.modelos[resultado.tipo])
        return modelo.format(**self._campos(resultado)).strip()

    def _sugestao(self, resultado: ResultadoDialogo) -> str:
        acao = resultado.acao_pendente
        remarcando = acao is not None and acao.tipo == TipoAcao.REMARCAR
        lista = acao is not None and acao.aguardando_escolha and len(resultado.opcoes) > 1
        avisos = self._avisos(resultado, lista)
        campos = {**self._campos(resultado), "avisos": f"{avisos} " if avisos else ""}
        if lista:
            return self._lista_de_horarios(resultado, campos, remarcando)
        chave = "troca" if remarcando and resultado.consulta_atual else "proposta"
        return "\n".join(self.frases[f"{chave}_{parte}"].format(**campos) for parte in ("cabecalho", "opcao", "instrucao"))

    def _lista_de_horarios(self, resultado: ResultadoDialogo, campos: dict[str, str], remarcando: bool) -> str:
        if resultado.preambulo == Preambulo.ESCOLHA_PENDENTE:
            cabecalho = self.frases["escolha_pendente"]
        elif remarcando and resultado.consulta_atual:
            cabecalho = self.frases["cabecalho_lista_troca"].format(**campos)
        else:
            cabecalho = self.frases["cabecalho_lista"].format(**campos)
        itens = [self.item(posicao, opcao) for posicao, opcao in enumerate(resultado.opcoes, start=1)]
        return "\n".join([cabecalho, *itens, self.frases["instrucao_lista"]])

    def _lista_de_consultas(self, resultado: ResultadoDialogo, cabecalho: str, instrucao: str) -> str:
        opcoes = resultado.opcoes
        if resultado.tipo == TipoResultado.LISTA_CONSULTAS:
            opcoes = opcoes[:self.consultas_listadas]
        if resultado.preambulo == Preambulo.ESCOLHA_PENDENTE:
            cabecalho = "escolha_pendente_consulta"
        itens = [self.item_de_consulta(posicao, opcao) for posicao, opcao in enumerate(opcoes, start=1)]
        rodape = self.frases[instrucao]
        if resultado.tipo == TipoResultado.LISTA_CONSULTAS and len(resultado.opcoes) > len(opcoes):
            rodape = self.frases["mais_consultas"]
        return "\n".join([self.frases[cabecalho], *itens, rodape])

    def _esclarecimento(self, resultado: ResultadoDialogo) -> str:
        atual = self.frases["consulta_atual_mantida"] if resultado.consulta_atual else ""
        if resultado.dia is not None:
            dia = f"{DIAS_DA_SEMANA[resultado.dia.weekday()]}, {self._data_curta(resultado.dia)}"
            pergunta = self.frases["opcao_ou_dia"].format(
                n=resultado.numero, quando=self.describe_when(resultado.opcao), dia=dia
            )
            return "\n".join(filter(None, (atual, pergunta)))
        itens = [self.item(posicao, opcao) for posicao, opcao in enumerate(resultado.opcoes, start=1)]
        return "\n".join(filter(None, (atual, self.frases["varias_combinam"], *itens, self.frases["instrucao_lista"])))

    def _opcao_inexistente(self, resultado: ResultadoDialogo) -> str:
        consultas = resultado.tipo in (
            TipoResultado.ORIENTAR_REMARCACAO, TipoResultado.CANCELAMENTO_AMBIGUO, TipoResultado.GERENCIAR_CONSULTAS
        )
        opcoes = resultado.opcoes or ((resultado.opcao,) if resultado.opcao else ())
        hora = resultado.hora_mencionada
        nao_mostrado = self.frases["hora_nao_mostrada"].format(hora=hora) if hora else ""
        if not opcoes:
            return self._corpo(replace(resultado, preambulo=None))
        if resultado.tipo == TipoResultado.SUGESTAO_HORARIO and len(opcoes) == 1:
            numero = resultado.numero
            inexistente = self.frases["numero_inexistente"].format(n=numero) if numero is not None else ""
            escolhido = self.frases["so_um_horario"].format(**self._campos(resultado))
            return " ".join(filter(None, (nao_mostrado, inexistente, escolhido)))
        unidade = ("consulta", "consultas", True) if consultas else ("horário", "horários", False)
        mostrei = f"Mostrei {quantidade(len(opcoes), *unidade)}."
        if len(opcoes) == 2:
            pergunta = self.frases["prefere"].format(opcoes=_juntar(referencias_distintivas(opcoes)))
        else:
            pergunta = self.frases["numeros_validos"].format(total=len(opcoes))
        return " ".join(filter(None, (nao_mostrado, mostrei, pergunta)))

    def _sem_horarios(self, resultado: ResultadoDialogo) -> str:
        campos = self._campos(resultado)
        partes = [self._avisos(resultado, lista=False)]
        if resultado.acao_pendente is not None and resultado.acao_pendente.tipo == TipoAcao.REMARCAR:
            partes.append(self.frases["consulta_atual_mantida"])
        if resultado.detalhe:
            partes.append(resultado.detalhe)
        else:
            chave = "sem_vaga_no_periodo" if resultado.periodo or (resultado.pedido and resultado.pedido.turno) else "sem_vaga"
            partes.append(self.frases[chave].format(**{**campos, "periodo": self._pedido(resultado)}))
        return "\n".join(parte for parte in partes if parte)

    @staticmethod
    def _data_curta(dia: date) -> str:
        return f"{dia.day} de {MESES[dia.month - 1]}"


class SimplifiedStyle(ResponseStyle):
    nome = "passo_a_passo"
    consultas_listadas = 2
    avisos = {
        Aviso.ESPECIALIDADE_PADRAO: "Como você não indicou uma especialidade, procurei Clínica Geral.",
        Aviso.HORARIO_RESERVADO: (
            "Essa opção não está mais disponível: o horário acabou de ser ocupado por outra pessoa e nada foi marcado."
        ),
        Aviso.OPCOES_REDUZIDAS: "Um dos horários que mostrei já foi ocupado.",
        Aviso.HORARIO_PEDIDO_INDISPONIVEL: "Não há vaga {hora} nesse dia.",
        Aviso.ESCOLHA_AUTOMATICA: "Escolhi o horário mais próximo.",
    }
    preambulos = {
        Preambulo.AJUDA: "Calma, vou repetir. {garantia}",
        Preambulo.NAO_ENTENDI: "Não entendi. {garantia}",
        Preambulo.RETOMADA: "Continuando de onde paramos. {garantia}",
        Preambulo.BOTAO_ANTIGO: "Esse botão era de uma pergunta anterior e não vale mais. Nada foi alterado.",
        Preambulo.ESTILO_PASSO_A_PASSO: "Certo, vou explicar passo a passo.",
        Preambulo.ESTILO_DIRETO: "Certo, vou ser mais direto.",
        Preambulo.ESTILO_AUTOMATICO: "Certo, vou ajustar o jeito de explicar durante a conversa.",
        Preambulo.MAIS_OPCOES: "Certo, vou mostrar mais horários de cada vez.",
        Preambulo.LIMITE_MEDICO: "Não posso indicar remédios nem dizer qual é a doença; isso é com o médico.",
        Preambulo.SOCIAL: "Estou aqui. Vamos continuar:",
        Preambulo.CONSULTA_MUDOU: "Essa consulta mudou desde a pergunta anterior e nada foi alterado. Confira de novo:",
    }
    garantias = {
        "agendar": "Ainda não marquei nada:",
        "remarcar": "Sua consulta ainda não mudou:",
        "cancelar": "Sua consulta continua marcada:",
        "solicitacao": "Sua consulta ainda não mudou; a clínica espera a sua resposta:",
        "nenhum": "",
    }
    situacoes = {
        "agendar": "Ainda não. A consulta só fica marcada depois que você confirmar:",
        "agendar_lista": "Ainda não marquei nada. Primeiro escolha um horário:",
        "remarcar": "Ainda não. A troca só acontece depois que você confirmar:",
        "cancelar": "Ainda não. A consulta só é desmarcada depois que você confirmar:",
        "solicitacao": "Ainda não. Nada muda antes da sua resposta:",
        "nenhum": "Para conferir o que está marcado, toque em Minhas consultas.",
    }
    frases = {
        "item": "{n}) {quando}, com {medico}",
        "proposta_cabecalho": "{avisos}Horário livre {com_especialidade}:",
        "proposta_opcao": "{quando}, com {medico}.",
        "proposta_instrucao": "Ainda não marquei. Para marcar, escreva SIM ou toque em Confirmar horário.",
        "troca_cabecalho": "{avisos}Confira a troca antes de confirmar:",
        "troca_opcao": "Sua consulta agora: {quando_atual}, com {medico_atual}.\nNovo horário: {quando}, com {medico}.",
        "troca_instrucao": "Para trocar, toque em Confirmar troca ou escreva SIM; para manter, escreva NÃO.",
        "cabecalho_lista": "{avisos}Horários livres {com_especialidade} (ainda não marquei nada):",
        "cabecalho_lista_troca": (
            "{avisos}Sua consulta de {quando_atual} continua marcada até você confirmar. Horários livres para a troca:"
        ),
        "instrucao_lista": "Toque no horário que preferir ou escreva o número; para ver outros, escreva MAIS HORÁRIOS.",
        "escolha_pendente": "Você disse sim; escolha um destes horários:",
        "escolha_pendente_consulta": "Você disse sim; escolha uma destas consultas:",
        "fora_lista": "Não há vaga {periodo}. Encontrei estas alternativas, fora do período pedido:",
        "fora_unica": "Não há vaga {periodo}; a próxima vaga está fora do período pedido.",
        "varias_combinam": "Mais de um horário combina com o que você escreveu:",
        "opcao_ou_dia": "Você quer o horário {n}, {quando}, ou prefere procurar vaga na {dia}?",
        "hora_nao_mostrada": "Não mostrei horário às {hora}.",
        "numero_inexistente": "Não há opção {n}.",
        "so_um_horario": "O horário que você escolheu é {quando}, com {medico}; para marcar, escreva SIM.",
        "prefere": "Você prefere {opcoes}?",
        "numeros_validos": "Toque no horário que preferir ou escreva um número de 1 a {total}.",
        "cabecalho_origem": "Escolha a consulta que você quer mudar (ela só muda depois da sua confirmação):",
        "cabecalho_desmarcar": "Escolha a consulta que você quer desmarcar:",
        "cabecalho_gerenciar": "Escolha a consulta que você quer mudar ou desmarcar:",
        "cabecalho_lista_consultas": "Suas próximas consultas:",
        "instrucao_consulta": "Toque na consulta ou escreva o número.",
        "instrucao_lista_consultas": "Para mudar ou desmarcar, toque em Mudar ou cancelar.",
        "mais_consultas": "Veja todas em Minhas consultas.",
        "consulta_atual_mantida": "Sua consulta atual continua marcada.",
        "sem_vaga": "Não achei vaga livre {com_especialidade} agora.\nNada foi marcado.\nA recepção pode avisar quando abrirem novas vagas.",
        "sem_vaga_no_periodo": (
            "Não achei vaga {com_especialidade} {periodo} nem nas datas seguintes.\nNada foi marcado.\n"
            "A recepção pode avisar quando abrirem novas vagas."
        ),
        "sem_profissional_final": (
            "Não há {especialidade} cadastrado nesta clínica.\nPor favor, fale com a recepção."
        ),
        "pergunta_inicial": "O que você quer fazer? Toque em uma opção abaixo.",
        "consulta_mantida": "Tudo bem. Sua consulta continua marcada:\n{quando}, com {medico}.",
        "troca_registrada": (
            "Pronto! Sua consulta mudou.\nAgora é {quando}, com {medico}.\nO horário antigo, {quando_atual}, ficou livre."
        ),
    }
    modelos = {
        TipoResultado.CONSULTA_AGENDADA: (
            "Pronto! Sua consulta está marcada.\n{quando}, com {medico}.\nEla aparece em Minhas consultas."
        ),
        TipoResultado.SUGESTAO_HORARIO: "{quando}, com {medico}.",
        TipoResultado.ESCLARECER_OPCAO: "Qual destes horários você quer?",
        TipoResultado.HORARIO_RESERVADO: (
            "Este horário acabou de ser ocupado por outra pessoa.\nNada foi marcado.\nEscreva outro dia que eu procuro."
        ),
        TipoResultado.SEM_HORARIOS: "Não achei vaga {com_especialidade}.\nNada foi marcado.",
        TipoResultado.SEM_PROFISSIONAL: (
            "Não há {especialidade} cadastrado nesta clínica.\nPosso procurar um clínico geral para você?"
        ),
        TipoResultado.MEDICO_NAO_ENCONTRADO: "Não encontrei esse médico.\nInforme o nome completo ou a especialidade.",
        TipoResultado.MEDICO_AMBIGUO: "Mais de um médico tem esse nome: {medicos}.\nQual nome completo você procura?",
        TipoResultado.FALTA_ESPECIALIDADE: "Qual especialidade você procura?\nExemplo: médico do coração.",
        TipoResultado.CONFIRMAR_CANCELAMENTO: (
            "Você quer desmarcar esta consulta?\n{quando}, com {medico}.\n"
            "Para desmarcar, toque em Desmarcar consulta ou escreva SIM; para manter, escreva NÃO."
        ),
        TipoResultado.CONSULTA_CANCELADA: (
            "Pronto! Sua consulta foi desmarcada.\nEra {quando}, com {medico}.\nO horário ficou livre."
        ),
        TipoResultado.CONSULTA_NAO_ENCONTRADA: (
            "Não encontrei uma consulta marcada {periodo}.\nPara conferir, toque em Minhas consultas."
        ),
        TipoResultado.CANCELAMENTO_AMBIGUO: "Escolha a consulta que você quer desmarcar:",
        TipoResultado.GERENCIAR_CONSULTAS: "Escolha a consulta que você quer mudar ou desmarcar:",
        TipoResultado.ESCOLHER_ACAO: (
            "Sua consulta: {quando}, com {medico}.\nO que você quer fazer: mudar o horário ou desmarcar?"
        ),
        TipoResultado.LISTA_CONSULTAS: "Suas próximas consultas:",
        TipoResultado.SEM_CONSULTAS: "Você não tem consultas marcadas.\nPara marcar, toque em Marcar consulta.",
        TipoResultado.AGENDAMENTO_DESCARTADO: "Tudo bem. Não marquei nada.",
        TipoResultado.CANCELAMENTO_DESCARTADO: "Tudo bem. Sua consulta continua marcada.",
        TipoResultado.ORIENTAR_REMARCACAO: (
            "Sua consulta continua marcada até você confirmar a troca:\n{quando}, com {medico}.\n"
            "Para qual dia você quer mudar? Exemplo: segunda à tarde."
        ),
        TipoResultado.REGRA_VIOLADA: "{detalhe}",
        TipoResultado.ORIENTACAO_MEDICA_BLOQUEADA: (
            "Não posso indicar remédios nem dizer qual é a doença.\nIsso precisa ser avaliado por um médico.\n"
            "Quer que eu procure um horário com clínico geral?"
        ),
        TipoResultado.SAUDACAO: "Olá! O que você quer fazer?\nToque em uma opção abaixo.",
        TipoResultado.AGRADECIMENTO: "De nada! Estou aqui se precisar.",
        TipoResultado.AJUDA: (
            "Eu ajudo a marcar, ver, mudar ou desmarcar consultas.\n"
            "Toque em uma opção abaixo ou escreva, por exemplo: quero marcar consulta."
        ),
        TipoResultado.PACIENTE_NAO_CADASTRADO: (
            "Não encontrei seu cadastro de paciente.\nFale com a recepção para concluir o cadastro."
        ),
        TipoResultado.SOLICITACAO_REMARCACAO: (
            "{solicitante} pediu para mudar sua consulta.\nDe {quando} para {quando_novo}, com {medico_novo}.\n"
            "Para aceitar, toque em Confirmar troca ou escreva SIM; para manter, escreva NÃO."
        ),
        TipoResultado.SOLICITACAO_CANCELAMENTO: (
            "{solicitante} pediu para desmarcar sua consulta.\n{quando}, com {medico}.\n"
            "Para aceitar, toque em Desmarcar consulta ou escreva SIM; para manter, escreva NÃO."
        ),
        TipoResultado.SOLICITACAO_INDISPONIVEL: (
            "Não consegui fazer a troca: o novo horário acabou de ser ocupado.\n"
            "Sua consulta continua: {quando}, com {medico}.\nA recepção pode combinar outro horário."
        ),
        TipoResultado.REMARCACAO_ACEITA: "Pronto! Sua consulta mudou.\nAgora é {quando}, com {medico}.",
        TipoResultado.CANCELAMENTO_ACEITO: (
            "Pronto! Sua consulta foi desmarcada.\nEra {quando}, com {medico}.\nO horário ficou livre."
        ),
        TipoResultado.SOLICITACAO_RECUSADA: (
            "Tudo bem. Sua consulta continua como estava:\n{quando}, com {medico}.\nA clínica vai ser avisada."
        ),
    }
    ja_registrados = {
        TipoResultado.CONSULTA_AGENDADA: (
            "Essa consulta já estava marcada para você.\n{quando}, com {medico}.\nNenhuma reserva nova foi feita."
        ),
        TipoResultado.CONSULTA_CANCELADA: "Essa consulta já estava desmarcada.\nEra {quando}, com {medico}.",
        TipoResultado.REMARCACAO_ACEITA: "Essa troca já estava feita.\nSua consulta é {quando}, com {medico}.",
    }

    def describe_when(self, opcao: OpcaoAgenda) -> str:
        return f"{DIAS_DA_SEMANA[opcao.data.weekday()]}, {self._data_curta(opcao.data)}, {self.describe_hour(opcao.hora)}"

    def describe_specialty(self, especialidade: str | None) -> str:
        return termo_leigo(especialidade) if especialidade else "médico dessa especialidade"

    def describe_hour(self, hora: str) -> str:
        horas, minutos = (int(parte) for parte in hora.split(":"))
        if minutos:
            return f"às {horas}h{minutos:02d}"
        return "à 1 hora" if horas == 1 else f"às {horas} horas"

    def describe_doctors(self, medicos: Sequence[str]) -> str:
        return "; ".join(medicos[:4]) + ("; há outros nomes — informe o nome completo" if len(medicos) > 4 else "")

    def describe_period(self, periodo: IntervaloDatas | None) -> str:
        if periodo is None:
            return "nesses dias"
        if periodo.inicio == periodo.fim:
            return f"no dia {periodo.inicio.day} de {MESES[periodo.inicio.month - 1]}"
        if periodo.inicio.month == periodo.fim.month:
            return f"entre os dias {periodo.inicio.day} e {periodo.fim.day} de {MESES[periodo.fim.month - 1]}"
        return (
            f"entre {periodo.inicio.day} de {MESES[periodo.inicio.month - 1]} "
            f"e {periodo.fim.day} de {MESES[periodo.fim.month - 1]}"
        )

    def _com_especialidade(self, especialidade: str | None) -> str:
        termo = self.describe_specialty(especialidade)
        return f"com o {termo}" if termo.startswith(("médico", "clínico")) else f"em {termo}"


class StandardStyle(ResponseStyle):
    nome = "direto"
    consultas_listadas = 6
    avisos = {
        Aviso.ESPECIALIDADE_PADRAO: "Como você não indicou uma especialidade, busquei Clínica Geral.",
        Aviso.HORARIO_RESERVADO: (
            "Essa opção não está mais disponível: o horário acabou de ser reservado por outro paciente. "
            "Nada foi marcado."
        ),
        Aviso.OPCOES_REDUZIDAS: "Parte dos horários mostrados antes já foi ocupada.",
        Aviso.HORARIO_PEDIDO_INDISPONIVEL: "O horário solicitado ({hora}) não está disponível nesse dia.",
        Aviso.ESCOLHA_AUTOMATICA: "Selecionei o horário mais próximo.",
    }
    preambulos = {
        Preambulo.AJUDA: "Sem problema. {garantia}",
        Preambulo.NAO_ENTENDI: "Não entendi a resposta. {garantia}",
        Preambulo.RETOMADA: "Retomando a conversa. {garantia}",
        Preambulo.BOTAO_ANTIGO: "Esse botão pertence a uma pergunta anterior e foi ignorado. Nada foi alterado.",
        Preambulo.ESTILO_PASSO_A_PASSO: "Certo, vou explicar passo a passo.",
        Preambulo.ESTILO_DIRETO: "Certo, serei mais direto.",
        Preambulo.ESTILO_AUTOMATICO: "Certo, vou ajustar a forma de explicar ao longo da conversa.",
        Preambulo.MAIS_OPCOES: "Certo, vou mostrar mais horários de cada vez.",
        Preambulo.LIMITE_MEDICO: (
            "Não posso indicar medicamentos nem fazer diagnósticos; isso cabe ao médico. Sobre o seu agendamento:"
        ),
        Preambulo.SOCIAL: "Estou aqui. Retomando:",
        Preambulo.CONSULTA_MUDOU: "A consulta foi alterada desde a pergunta anterior; nada foi feito. Confira os dados atuais:",
    }
    garantias = {
        "agendar": "Nada foi marcado ainda. Repetindo a última pergunta:",
        "remarcar": "A consulta atual não foi alterada. Repetindo a última pergunta:",
        "cancelar": "A consulta continua marcada. Repetindo a última pergunta:",
        "solicitacao": "A consulta não foi alterada; a clínica aguarda a sua resposta:",
        "nenhum": "",
    }
    situacoes = {
        "agendar": "Ainda não: a consulta só é marcada depois da sua confirmação.",
        "agendar_lista": "Ainda não: escolha um horário e confirme para marcar.",
        "remarcar": "Ainda não: a troca só é feita depois da sua confirmação.",
        "cancelar": "Ainda não: a consulta só é desmarcada depois da sua confirmação.",
        "solicitacao": "Ainda não: nada muda antes da sua resposta.",
        "nenhum": "Para conferir o que está marcado, abra \"Minhas consultas\".",
    }
    frases = {
        "item": "{n}. {quando} — {medico}",
        "proposta_cabecalho": "{avisos}Horário disponível em {especialidade_nome}:",
        "proposta_opcao": "{medico}, {quando}.",
        "proposta_instrucao": (
            "Confirma? Toque em Confirmar horário ou responda \"sim\"; para outra opção, \"outro\"; "
            "para desistir, \"não\". A consulta ainda não foi marcada."
        ),
        "troca_cabecalho": "{avisos}Confira a troca:",
        "troca_opcao": "Consulta atual: {quando_atual} — {medico_atual}.\nNovo horário: {quando} — {medico}.",
        "troca_instrucao": (
            "Confirma a troca? Toque em Confirmar troca ou responda \"sim\"; para manter a consulta atual, \"não\". "
            "A consulta atual só muda depois da confirmação."
        ),
        "cabecalho_lista": "{avisos}Horários disponíveis em {especialidade_nome}:",
        "cabecalho_lista_troca": (
            "{avisos}Consulta atual: {quando_atual} — {medico_atual} (continua marcada até a confirmação). "
            "Horários disponíveis para a troca:"
        ),
        "instrucao_lista": (
            "Escolha pelo número ou toque no horário. Para ver outras vagas, peça MAIS HORÁRIOS ou informe um dia. "
            "Nada foi marcado ainda."
        ),
        "escolha_pendente": "Há mais de uma opção; escolha um dos horários:",
        "escolha_pendente_consulta": "Há mais de uma consulta; escolha uma delas:",
        "fora_lista": "Não há vaga {periodo}. Estas são as alternativas mais próximas, fora do período pedido:",
        "fora_unica": "Não há vaga {periodo}; a alternativa mais próxima está fora do período pedido.",
        "varias_combinam": "Mais de um horário corresponde ao que você escreveu:",
        "opcao_ou_dia": "Você quer a opção {n} ({quando}) ou prefere buscar horários na {dia}?",
        "hora_nao_mostrada": "Não mostrei horário às {hora}.",
        "numero_inexistente": "Não há opção {n}.",
        "so_um_horario": "O horário selecionado é {quando} — {medico}; para marcar, responda \"sim\".",
        "prefere": "Você prefere {opcoes}?",
        "numeros_validos": "Responda com um número de 1 a {total} ou toque no horário.",
        "cabecalho_origem": "Qual consulta você quer remarcar? A atual é mantida até a confirmação:",
        "cabecalho_desmarcar": "Você tem mais de uma consulta nesse critério. Qual deseja cancelar?",
        "cabecalho_gerenciar": "Qual consulta você quer alterar ou cancelar?",
        "cabecalho_lista_consultas": "Suas próximas consultas:",
        "instrucao_consulta": "Responda com o número ou toque na consulta.",
        "instrucao_lista_consultas": "Para remarcar ou cancelar, toque em Mudar ou cancelar.",
        "mais_consultas": "A lista completa está em \"Minhas consultas\".",
        "consulta_atual_mantida": "A consulta atual continua marcada.",
        "sem_vaga": (
            "Não há horários disponíveis em {especialidade_nome} no momento. Nenhuma consulta foi marcada. "
            "A recepção pode informar sobre a liberação de novas vagas."
        ),
        "sem_vaga_no_periodo": (
            "Não há horários disponíveis em {especialidade_nome} {periodo} nem nas datas seguintes. "
            "Nenhuma consulta foi marcada. A recepção pode informar sobre a liberação de novas vagas."
        ),
        "sem_profissional_final": (
            "Não há profissional de {especialidade_nome} cadastrado na clínica. Procure a recepção."
        ),
        "pergunta_inicial": "Como posso ajudar?",
        "consulta_mantida": "Ok, a consulta foi mantida: {quando} — {medico}.",
        "troca_registrada": (
            "Remarcação confirmada: sua consulta agora é {quando} — {medico}. O horário anterior ({quando_atual}) "
            "foi liberado. A nova data já aparece em \"Minhas consultas\"."
        ),
    }
    modelos = {
        TipoResultado.CONSULTA_AGENDADA: (
            "Consulta agendada com {medico} ({especialidade}) em {quando}. Ela já aparece em \"Minhas consultas\"."
        ),
        TipoResultado.SUGESTAO_HORARIO: "Horário disponível em {especialidade}: {medico}, {quando}.",
        TipoResultado.ESCLARECER_OPCAO: "Qual destes horários você prefere?",
        TipoResultado.HORARIO_RESERVADO: (
            "Este horário acabou de ser reservado por outro paciente. "
            "Não encontrei outra opção com os mesmos critérios; informe outra data ou período."
        ),
        TipoResultado.SEM_HORARIOS: "Não há horários disponíveis em {especialidade} {periodo}.",
        TipoResultado.SEM_PROFISSIONAL: (
            "Não há profissional de {especialidade_nome} cadastrado na clínica. "
            "Deseja que eu busque horários em Clínica Geral?"
        ),
        TipoResultado.MEDICO_NAO_ENCONTRADO: (
            "Não encontrei médico com esse nome. Verifique a grafia ou informe a especialidade desejada."
        ),
        TipoResultado.MEDICO_AMBIGUO: "Há mais de um médico com esse nome: {medicos}. Qual deles você prefere?",
        TipoResultado.FALTA_ESPECIALIDADE: (
            "Para qual especialidade ou médico deseja agendar? "
            "Ex.: \"cardiologia amanhã às 10h\" ou \"Dra. Maria dia 25/10 às 14h\"."
        ),
        TipoResultado.CONFIRMAR_CANCELAMENTO: (
            "Confirma o cancelamento da consulta com {medico} ({especialidade}) em {quando}? "
            "Toque em Desmarcar consulta ou responda \"sim\"; para manter, toque em Manter minha consulta "
            "ou responda \"não\"."
        ),
        TipoResultado.CONSULTA_CANCELADA: (
            "Consulta com {medico} em {quando} cancelada. O horário foi liberado e a clínica foi avisada."
        ),
        TipoResultado.CONSULTA_NAO_ENCONTRADA: (
            "Não encontrei consulta agendada {periodo}. Confira em \"Minhas consultas\"."
        ),
        TipoResultado.CANCELAMENTO_AMBIGUO: "Você possui mais de uma consulta nesse critério.",
        TipoResultado.GERENCIAR_CONSULTAS: "Qual consulta você quer alterar ou cancelar?",
        TipoResultado.ESCOLHER_ACAO: "Consulta: {quando} — {medico} ({especialidade}). Deseja remarcar ou cancelar?",
        TipoResultado.LISTA_CONSULTAS: "Suas próximas consultas:",
        TipoResultado.SEM_CONSULTAS: "Você não possui consultas agendadas.",
        TipoResultado.AGENDAMENTO_DESCARTADO: "Ok, nenhum agendamento foi feito.",
        TipoResultado.CANCELAMENTO_DESCARTADO: "Ok, a consulta foi mantida.",
        TipoResultado.ORIENTAR_REMARCACAO: (
            "Consulta atual: {quando} — {medico} (continua marcada até a confirmação). "
            "Para qual dia ou período deseja remarcar? Você também pode pedir os horários livres."
        ),
        TipoResultado.REGRA_VIOLADA: "{detalhe}",
        TipoResultado.ORIENTACAO_MEDICA_BLOQUEADA: (
            "Como assistente virtual, não tenho permissão para realizar diagnósticos ou indicar medicamentos. "
            "Deseja agendar uma consulta com um Clínico Geral para avaliar seus sintomas?"
        ),
        TipoResultado.SAUDACAO: "Olá! Posso marcar, mostrar, remarcar ou cancelar consultas. Como posso ajudar?",
        TipoResultado.AGRADECIMENTO: "Por nada! Precisando, é só chamar.",
        TipoResultado.AJUDA: (
            "Não entendi a solicitação. Exemplos: \"agendar cardiologia amanhã às 10h\", "
            "\"minhas consultas\", \"cancelar consulta do dia 25/10\"."
        ),
        TipoResultado.PACIENTE_NAO_CADASTRADO: (
            "Não há cadastro de paciente vinculado ao seu usuário. Procure a recepção para concluir o cadastro."
        ),
        TipoResultado.SOLICITACAO_REMARCACAO: (
            "{solicitante} solicitou remarcar sua consulta com {medico} de {quando} para {quando_novo} "
            "com {medico_novo}. Toque em Confirmar troca (ou responda \"sim\") para aceitar, "
            "ou em Manter minha consulta (\"não\")."
        ),
        TipoResultado.SOLICITACAO_CANCELAMENTO: (
            "{solicitante} solicitou cancelar sua consulta com {medico} em {quando}. "
            "Toque em Desmarcar consulta (ou responda \"sim\") para aceitar, ou em Manter minha consulta (\"não\")."
        ),
        TipoResultado.SOLICITACAO_INDISPONIVEL: (
            "Não foi possível aceitar a remarcação: o novo horário acabou de ser ocupado. "
            "Sua consulta continua em {quando} com {medico}. A recepção pode propor outro horário."
        ),
        TipoResultado.REMARCACAO_ACEITA: (
            "Remarcação confirmada: sua consulta agora é {quando} — {medico}. "
            "A nova data já aparece em \"Minhas consultas\"."
        ),
        TipoResultado.CANCELAMENTO_ACEITO: (
            "Cancelamento confirmado: a consulta de {quando} com {medico} foi desmarcada e o horário liberado."
        ),
        TipoResultado.SOLICITACAO_RECUSADA: (
            "Solicitação recusada. Sua consulta foi mantida ({quando} — {medico}) e a clínica será avisada."
        ),
    }
    ja_registrados = {
        TipoResultado.CONSULTA_AGENDADA: (
            "Esta consulta já estava registrada: {medico} ({especialidade}) em {quando}. Nenhuma reserva nova foi criada."
        ),
        TipoResultado.CONSULTA_CANCELADA: "Esta consulta já estava cancelada: {medico} em {quando}.",
        TipoResultado.REMARCACAO_ACEITA: "A troca já estava registrada: sua consulta é {quando} — {medico}.",
    }

    def describe_when(self, opcao: OpcaoAgenda) -> str:
        return f"{opcao.data:%d/%m/%Y} ({DIAS_DA_SEMANA[opcao.data.weekday()]}) às {opcao.hora}"

    def describe_specialty(self, especialidade: str | None) -> str:
        return especialidade or "a especialidade pedida"

    def describe_hour(self, hora: str) -> str:
        return hora

    def describe_period(self, periodo: IntervaloDatas | None) -> str:
        if periodo is None:
            return "no período informado"
        if periodo.inicio == periodo.fim:
            return f"em {periodo.inicio:%d/%m/%Y}"
        return f"entre {periodo.inicio:%d/%m/%Y} e {periodo.fim:%d/%m/%Y}"

    def item_de_consulta(self, posicao: int, opcao: OpcaoAgenda) -> str:
        return f"{posicao}. {opcao.data:%d/%m/%Y} às {opcao.hora} — {opcao.medico} ({opcao.especialidade})"


class BotoesDaResposta:
    """Botões que nomeiam a ação; todos levam a proposta da pergunta que os criou."""

    ABERTURA = (("marcar_consulta", "Marcar consulta"), ("minhas_consultas", "Minhas consultas"),
                ("mudar_ou_cancelar", "Mudar ou cancelar"))

    def montar(self, estilo: EstiloComunicacao, resultado: ResultadoDialogo) -> list[OpcaoDeResposta]:
        acao = resultado.acao_pendente
        if acao is None:
            return self._sem_pergunta(resultado)
        direto = estilo == EstiloComunicacao.DIRETO

        def botao(codigo: str, rotulo: str, valor: str | None = None) -> OpcaoDeResposta:
            return OpcaoDeResposta(codigo=codigo, rotulo=rotulo, proposta=acao.proposta, valor=valor)

        match acao.pergunta:
            case Pergunta.CONFIRMAR_HORARIO:
                botoes = [botao("confirmar_horario", "Confirmar horário"), botao("outro_horario", "Ver outro horário")]
                return botoes + ([botao("nao_marcar", "Não marcar agora")] if direto else [])
            case Pergunta.CONFIRMAR_TROCA:
                return [botao("confirmar_troca", "Confirmar troca"), botao("manter_consulta", "Manter minha consulta")]
            case Pergunta.CONFIRMAR_DESMARCACAO:
                return [botao("desmarcar_consulta", "Desmarcar consulta"), botao("manter_consulta", "Manter minha consulta")]
            case Pergunta.RESPONDER_SOLICITACAO:
                confirmar = ("confirmar_troca", "Confirmar troca") if acao.solicitacao == "remarcacao" else (
                    "desmarcar_consulta", "Desmarcar consulta")
                return [botao(*confirmar), botao("manter_consulta", "Manter minha consulta")]
            case Pergunta.ESCOLHER_ACAO:
                return [botao("mudar_horario", "Mudar o horário"), botao("desmarcar_esta", "Desmarcar esta consulta")]
            case Pergunta.INFORMAR_DESTINO:
                return [botao("buscar_horarios", "Ver horários livres"), botao("manter_consulta", "Manter minha consulta")]
            case Pergunta.NOVA_BUSCA if acao.origem in (
                TipoResultado.ORIENTACAO_MEDICA_BLOQUEADA, TipoResultado.SEM_PROFISSIONAL
            ):
                return [botao("buscar_horarios", "Procurar horário com clínico geral"), botao("nao_marcar", "Agora não")]
            case Pergunta.ESCOLHER_HORARIO if resultado.dia is not None and resultado.opcao:
                numero = resultado.numero or 1
                return [
                    botao("escolher", f"Horário {numero}: {rotulo_completo(resultado.opcao)}", str(numero)),
                    botao("buscar_dia", f"Procurar na {DIAS_DA_SEMANA[resultado.dia.weekday()]}", resultado.dia.isoformat()),
                ]
            case Pergunta.ESCOLHER_HORARIO | Pergunta.ESCOLHER_CONSULTA if resultado.opcoes:
                consultas = acao.pergunta == Pergunta.ESCOLHER_CONSULTA
                if consultas:
                    rotulos = [f"{rotulo_completo(opcao)} — {opcao.medico}" for opcao in resultado.opcoes]
                else:
                    rotulos = rotulos_curtos(resultado.opcoes)
                botoes = [botao("escolher", f"{n}. {rotulo}", str(n)) for n, rotulo in enumerate(rotulos, start=1)]
                paginavel = direto and not consultas and resultado.tipo == TipoResultado.SUGESTAO_HORARIO
                return botoes + ([botao("outro_horario", "Mais horários")] if paginavel else [])
        return []

    def _sem_pergunta(self, resultado: ResultadoDialogo) -> list[OpcaoDeResposta]:
        if resultado.tipo in (TipoResultado.SAUDACAO, TipoResultado.AJUDA, TipoResultado.AGENDAMENTO_DESCARTADO):
            return [OpcaoDeResposta(codigo=codigo, rotulo=rotulo) for codigo, rotulo in self.ABERTURA]
        if resultado.tipo == TipoResultado.SEM_CONSULTAS:
            return [OpcaoDeResposta(codigo="marcar_consulta", rotulo="Marcar consulta")]
        if resultado.tipo == TipoResultado.LISTA_CONSULTAS:
            return [OpcaoDeResposta(codigo="mudar_ou_cancelar", rotulo="Mudar ou cancelar"),
                    OpcaoDeResposta(codigo="marcar_consulta", rotulo="Marcar consulta")]
        return []


class ResponseDecisionTree:
    def __init__(self) -> None:
        self._estilos: dict[EstiloComunicacao, ResponseStyle] = {
            EstiloComunicacao.PASSO_A_PASSO: SimplifiedStyle(),
            EstiloComunicacao.DIRETO: StandardStyle(),
        }
        self._botoes = BotoesDaResposta()

    def choose_style(self, estilo: EstiloComunicacao) -> ResponseStyle:
        return self._estilos[estilo]

    def respond(self, estilo: EstiloComunicacao, resultado: ResultadoDialogo) -> RespostaComposta:
        return RespostaComposta(self.choose_style(estilo).write(resultado), self._botoes.montar(estilo, resultado))


