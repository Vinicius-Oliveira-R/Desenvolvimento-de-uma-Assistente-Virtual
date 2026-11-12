"""Respostas de agenda baseadas exclusivamente nos horários retornados pelo banco."""

from app.backend.assistant.dialogue import Aviso, ResultadoDialogo, TipoResultado
from app.backend.assistant.responses import DIAS_DA_SEMANA, ResponseDecisionTree


def describe_slot(option) -> str:
    return (
        f"{option.data:%d/%m/%Y} ({DIAS_DA_SEMANA[option.data.weekday()]}) "
        f"às {option.hora} — {option.medico}"
    )


class SchedulingResponseDecisionTree(ResponseDecisionTree):
    def respond(self, perfil, resultado: ResultadoDialogo) -> str:
        if resultado.tipo == TipoResultado.SEM_HORARIOS and resultado.detalhe:
            specialty = resultado.especialidade or "o médico solicitado"
            return f"Busca de consulta: {specialty}.\n{resultado.detalhe}"
        if resultado.tipo != TipoResultado.SUGESTAO_HORARIO:
            return super().respond(perfil, resultado)
        pending = resultado.acao_pendente
        # Uma única opção mantém a redação acessível já usada em cada perfil.
        if resultado.opcao and not (pending and pending.aguardando_escolha):
            text = super().respond(perfil, resultado)
            return f"{resultado.detalhe}\n{text}" if resultado.detalhe else text
        lines = []
        if resultado.detalhe:
            lines.append(resultado.detalhe)
        if resultado.aviso == Aviso.HORARIO_RESERVADO:
            lines.append("O horário anterior foi ocupado por outro paciente.")
        elif resultado.aviso == Aviso.HORARIO_PEDIDO_INDISPONIVEL:
            lines.append("Não há vaga no horário exato pedido.")
        pending = resultado.acao_pendente
        if pending and pending.aguardando_escolha:
            specialty = resultado.especialidade or resultado.opcoes[0].especialidade
            lines.append(f"Estes são os próximos horários livres em {specialty}:")
            lines.extend(f"{index}. {describe_slot(option)}" for index, option in enumerate(resultado.opcoes, 1))
            lines.append("Qual opção você prefere? Responda com o número, por exemplo: 2.")
            lines.append("Para consultar outras vagas, escreva MAIS HORÁRIOS ou informe um dia.")
            lines.append("Ainda não marquei a consulta.")
        elif resultado.opcao:
            lines.append(f"Consulta em {resultado.opcao.especialidade}:")
            lines.append(describe_slot(resultado.opcao))
            lines.append("Confirma esse agendamento? Responda SIM para marcar ou NÃO para desistir.")
            lines.append("Para consultar outra opção, escreva MAIS HORÁRIOS.")
        else:
            return super().respond(perfil, resultado)
        return "\n".join(lines)
