"""Estilo simplificado: até três unidades (sentenças ou itens) por resposta.

Cabeçalhos sem ponto final não contam; abreviações de nomes e datas não são
sentenças. Cada opção numerada conta como uma unidade, mesmo sem ponto final.
"""
import re

from app.backend.assistant.dialogue import TipoResultado
from app.backend.assistant.responses import SimplifiedStyle


def response_units(text: str) -> int:
    text = re.sub(r"\b(Dr|Dra|Sr|Sra)\.", r"\1", text, flags=re.I)
    units = 0
    for line in text.splitlines():
        if re.match(r"^\d+[).]\s", line):
            units += 1
        elif line.strip() and not line.rstrip().endswith(":"):
            units += max(1, len(re.findall(r"[.!?]+(?:\s|$)", line)))
    return units


class ConciseSimplifiedStyle(SimplifiedStyle):
    modelos = {
        **SimplifiedStyle.modelos,
        TipoResultado.CONSULTA_AGENDADA: "Pronto! Sua consulta está marcada.\n{quando} — {medico}",
        TipoResultado.SUGESTAO_HORARIO: "{especialidade}: {quando} — {medico}.\nPara marcar, escreva SIM; para outra vaga, OUTRO; para desistir, NÃO.",
        TipoResultado.HORARIO_RESERVADO: "Este horário acabou de ser reservado por outro paciente.\nPeça outra data; nenhuma nova consulta foi marcada.",
        TipoResultado.SEM_HORARIOS: "Não encontrei horários livres com {especialidade}.\nA recepção pode informar quando surgirem novas vagas.\nNenhuma consulta foi marcada.",
        TipoResultado.MEDICO_NAO_ENCONTRADO: "Não encontrei esse médico.\nInforme o nome completo ou a especialidade.",
        TipoResultado.MEDICO_AMBIGUO: "Mais de um médico tem esse nome: {medicos}.\nQual nome completo você procura?",
        TipoResultado.FALTA_ESPECIALIDADE: "Posso buscar Clínica Geral.\nPode ser?",
        TipoResultado.CONFIRMAR_CANCELAMENTO: "Deseja desmarcar {quando}, com {medico}?\nEscreva SIM para desmarcar ou NÃO para manter.",
        TipoResultado.CONSULTA_CANCELADA: "Sua consulta foi desmarcada.\nO horário ficou livre.",
        TipoResultado.CONSULTA_NAO_ENCONTRADA: "Não encontrei uma consulta nesse critério.\nEscreva MINHAS CONSULTAS para conferir.",
        TipoResultado.SEM_CONSULTAS: "Você não tem consultas marcadas.\nPara marcar, escreva MARCAR CONSULTA.",
        TipoResultado.AGENDAMENTO_DESCARTADO: "Tudo bem; nenhuma nova consulta foi marcada.",
        TipoResultado.CANCELAMENTO_DESCARTADO: "Tudo bem; sua consulta continua marcada.",
        TipoResultado.ORIENTACAO_MEDICA_BLOQUEADA: "Não posso indicar remédios nem dizer qual é a doença.\nPosso buscar uma consulta com clínico geral para avaliação?",
        TipoResultado.SAUDACAO: "Olá!\nPosso marcar, listar ou desmarcar consultas.\nO que você deseja fazer?",
        TipoResultado.AGRADECIMENTO: "De nada; estou aqui para ajudar com sua agenda.",
        TipoResultado.AJUDA: "Posso ajudar com a agenda.\nEscreva MARCAR CONSULTA, MINHAS CONSULTAS ou CANCELAR CONSULTA.",
        TipoResultado.PACIENTE_NAO_CADASTRADO: "Não encontrei seu cadastro de paciente.\nFale com a recepção para concluir o cadastro.",
        TipoResultado.SOLICITACAO_REMARCACAO: "{solicitante} pediu para mudar sua consulta de {quando} para {quando_novo}, com {medico_novo}.\nEscreva SIM para aceitar ou NÃO para manter.",
        TipoResultado.SOLICITACAO_CANCELAMENTO: "{solicitante} pediu para desmarcar {quando}, com {medico}.\nEscreva SIM para aceitar ou NÃO para manter.",
        TipoResultado.REMARCACAO_ACEITA: "A remarcação foi confirmada.\nConfira a nova data em Meus Agendamentos.",
        TipoResultado.CANCELAMENTO_ACEITO: "Sua consulta foi desmarcada.\nO horário ficou livre.",
        TipoResultado.SOLICITACAO_RECUSADA: "Sua consulta foi mantida.\nA clínica será avisada.",
    }

    def describe_when(self, option):
        return f"{self._data_por_extenso(option.data)}, {self._hora_por_extenso(option.hora)}"

    def describe_doctors(self, doctors):
        return "; ".join(doctors[:4]) + ("; há outros nomes — informe o nome completo" if len(doctors) > 4 else "")
