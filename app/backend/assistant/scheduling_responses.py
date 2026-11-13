"""Respostas baseadas somente nas opções reais; reserva nunca é presumida."""
from app.backend.assistant.concise_responses import ConciseSimplifiedStyle
from app.backend.assistant.dialogue import Aviso, ResultadoDialogo, TipoResultado
from app.backend.assistant.responses import DIAS_DA_SEMANA, ResponseDecisionTree
from app.backend.ml.profile_classifier import PerfilEtario
from app.backend.schemas.assistant import TipoAcao


def describe_slot(option) -> str:
    return f"{option.data:%d/%m/%Y} ({DIAS_DA_SEMANA[option.data.weekday()]}) às {option.hora} — {option.medico}"


class SchedulingResponseDecisionTree(ResponseDecisionTree):
    def __init__(self):
        super().__init__()
        self._estilos[PerfilEtario.IDOSO] = ConciseSimplifiedStyle()

    def respond(self, perfil, resultado: ResultadoDialogo) -> str:
        simple = perfil == PerfilEtario.IDOSO
        pending = resultado.acao_pendente
        if resultado.tipo == TipoResultado.ORIENTAR_REMARCACAO and pending and pending.tipo == TipoAcao.REMARCAR:
            if resultado.opcoes:
                options = resultado.opcoes[:2] if simple else resultado.opcoes
                lines = ["Consulta que deseja remarcar (a atual será mantida até a confirmação):"]
                lines += [f"{i}) {describe_slot(option)}" for i, option in enumerate(options, 1)]
                return "\n".join([*lines, "Escolha pelo número ou peça MAIS CONSULTAS."])
            return f"Consulta atual: {describe_slot(resultado.opcao)}.\nInforme o novo dia ou peça HORÁRIOS LIVRES; sua consulta permanece marcada."
        if simple and resultado.tipo in (TipoResultado.LISTA_CONSULTAS, TipoResultado.CANCELAMENTO_AMBIGUO):
            lines = ["Suas próximas consultas:"]
            lines += [f"{i}) {describe_slot(option)}" for i, option in enumerate(resultado.opcoes[:2], 1)]
            instruction = "Para cancelar, informe dia e hora; outras consultas estão em Meus Agendamentos." if resultado.tipo == TipoResultado.CANCELAMENTO_AMBIGUO else "Consulte a lista completa em Meus Agendamentos."
            return "\n".join([*lines, instruction])
        if resultado.tipo == TipoResultado.SEM_HORARIOS and resultado.detalhe:
            if simple:
                return self.choose_style(perfil).write(resultado)
            return f"Busca de consulta: {resultado.especialidade or 'o médico solicitado'}.\n{resultado.detalhe}"
        if resultado.tipo != TipoResultado.SUGESTAO_HORARIO:
            return super().respond(perfil, resultado)
        moving = pending and pending.tipo == TipoAcao.REMARCAR
        if moving and not pending.aguardando_escolha:
            return f"Novo horário: {describe_slot(resultado.opcao)}.\nConfirma a troca, mantendo a consulta atual se houver conflito?\nResponda SIM para confirmar ou NÃO para manter a atual."
        if simple:
            lines = []
            if pending and pending.aguardando_escolha:
                specialty = self.choose_style(perfil).describe_specialty(resultado.especialidade or resultado.opcoes[0].especialidade)
                note = "alternativas fora do período pedido" if resultado.detalhe and "alternativas" in resultado.detalhe else "horários livres"
                if resultado.aviso:
                    note = "o horário anterior está indisponível; alternativas"
                lines.append(f"{specialty.capitalize()} — {note} (nenhuma consulta alterada):")
                lines += [f"{i}) {describe_slot(option)}" for i, option in enumerate(resultado.opcoes[:2], 1)]
                lines.append("Responda com o número ou peça MAIS HORÁRIOS.")
                return "\n".join(lines)
            text = super().respond(perfil, resultado)
            note = resultado.detalhe or ""
            if "não indicou uma especialidade" in note:
                prefix = "Como você não indicou uma especialidade, busquei Clínica Geral"
                if "alternativas" in note:
                    prefix += "; esta opção está fora do período pedido"
                text = prefix + ".\n" + text
            elif "alternativas" in note:
                text = "Não há vaga no período pedido; esta é uma alternativa.\n" + text
            elif "não está mais disponível" in note or resultado.aviso:
                text = "Essa opção não está mais disponível; segue outra.\n" + text
            return text
        if resultado.opcao and not (pending and pending.aguardando_escolha):
            text = super().respond(perfil, resultado)
            return f"{resultado.detalhe}\n{text}" if resultado.detalhe else text
        lines = [resultado.detalhe] if resultado.detalhe else []
        if resultado.aviso:
            lines.append("O horário anterior está indisponível; confira as alternativas.")
        specialty = resultado.especialidade or resultado.opcoes[0].especialidade
        lines.append(f"Estes são os próximos horários livres em {specialty}:")
        lines += [f"{i}. {describe_slot(option)}" for i, option in enumerate(resultado.opcoes, 1)]
        lines += ["Qual opção você prefere? Responda com o número.", "Para outras vagas, escreva MAIS HORÁRIOS ou informe um dia.", "Ainda não alterei a agenda."]
        return "\n".join(lines)
