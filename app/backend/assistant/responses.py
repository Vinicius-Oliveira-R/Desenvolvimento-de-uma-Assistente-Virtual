"""Árvore de decisão determinística da resposta adaptativa.

Nível 1 - perfil etário previsto pelo Random Forest: IDOSO -> estilo simplificado; PADRAO -> estilo padrão.
Nível 2 - resultado do diálogo (TipoResultado) -> modelo de mensagem do estilo escolhido.
Nível 3 - dados opcionais (aviso de conflito, período, listas) completam a mensagem final.

O estilo simplificado segue diretrizes de linguagem simples: frases curtas com uma ideia cada,
termos leigos no lugar de especialidades técnicas, datas por extenso e instruções numeradas.
"""

from abc import ABC, abstractmethod
from collections.abc import Sequence
from datetime import date
from typing import ClassVar

from app.backend.assistant.dialogue import Aviso, OpcaoAgenda, ResultadoDialogo, TipoResultado
from app.backend.assistant.especialidades import termo_leigo
from app.backend.assistant.temporal import IntervaloDatas
from app.backend.ml.profile_classifier import PerfilEtario

DIAS_DA_SEMANA = ("segunda-feira", "terça-feira", "quarta-feira", "quinta-feira", "sexta-feira", "sábado", "domingo")
MESES = (
    "janeiro", "fevereiro", "março", "abril", "maio", "junho",
    "julho", "agosto", "setembro", "outubro", "novembro", "dezembro",
)


class ResponseStyle(ABC):
    nome: ClassVar[str]
    modelos: ClassVar[dict[TipoResultado, str]]
    avisos: ClassVar[dict[Aviso, str]]

    def write(self, resultado: ResultadoDialogo) -> str:
        opcao = resultado.opcao
        campos = {
            "aviso": self.avisos[resultado.aviso] if resultado.aviso else "",
            "medico": opcao.medico if opcao else "",
            "quando": self.describe_when(opcao) if opcao else "",
            "especialidade": self.describe_specialty(resultado.especialidade or (opcao.especialidade if opcao else "")),
            "lista": self.describe_list(resultado.opcoes),
            "medicos": self.describe_doctors(resultado.medicos),
            "periodo": self.describe_period(resultado.periodo),
            "detalhe": resultado.detalhe or "",
        }
        return self.modelos[resultado.tipo].format(**campos).strip()

    @abstractmethod
    def describe_when(self, opcao: OpcaoAgenda) -> str: ...

    @abstractmethod
    def describe_specialty(self, especialidade: str) -> str: ...

    @abstractmethod
    def describe_list(self, opcoes: Sequence[OpcaoAgenda]) -> str: ...

    @abstractmethod
    def describe_doctors(self, medicos: Sequence[str]) -> str: ...

    @abstractmethod
    def describe_period(self, periodo: IntervaloDatas | None) -> str: ...


class SimplifiedStyle(ResponseStyle):
    nome = "simplificado"
    avisos = {
        Aviso.HORARIO_RESERVADO: "Este horário acabou de ser reservado por outro paciente.\n",
        Aviso.HORARIO_PEDIDO_INDISPONIVEL: "Não tem vaga no horário que você pediu.\n",
    }
    modelos = {
        TipoResultado.CONSULTA_AGENDADA: (
            "Pronto! Sua consulta está marcada.\n{quando}\nMédico: {medico}.\n"
            "Para ver suas consultas, toque em \"Meus Agendamentos\"."
        ),
        TipoResultado.SUGESTAO_HORARIO: (
            "{aviso}Achei um horário com o {especialidade}.\n{quando}\nMédico: {medico}.\n\n"
            "O que fazer agora:\n1. Para marcar, escreva SIM.\n2. Para ver outro horário, escreva OUTRO.\n"
            "3. Para desistir, escreva NÃO."
        ),
        TipoResultado.HORARIO_RESERVADO: (
            "Este horário acabou de ser reservado por outro paciente.\n"
            "Não achei outro horário parecido.\nEscreva outro dia que eu procuro para você."
        ),
        TipoResultado.SEM_HORARIOS: (
            "Não achei vaga com o {especialidade} {periodo}.\n"
            "Escreva outro dia que eu procuro de novo.\nExemplo: \"dia 20\"."
        ),
        TipoResultado.MEDICO_NAO_ENCONTRADO: (
            "Não achei esse médico.\nEscreva o nome de novo.\n"
            "Ou diga o tipo de médico. Exemplo: \"médico do coração\"."
        ),
        TipoResultado.MEDICO_AMBIGUO: (
            "Achei mais de um médico com esse nome:\n{medicos}\nEscreva o nome completo do médico."
        ),
        TipoResultado.FALTA_ESPECIALIDADE: (
            "Vou te ajudar a marcar.\nQue tipo de médico você precisa?\n"
            "Pode contar o que está sentindo. Exemplo: \"dor nas costas\".\n"
            "Se não souber, posso marcar com um clínico geral. Pode ser?"
        ),
        TipoResultado.CONFIRMAR_CANCELAMENTO: (
            "Você quer desmarcar esta consulta?\n{quando}\nMédico: {medico}.\n\n"
            "1. Para desmarcar, escreva SIM.\n2. Para manter a consulta, escreva NÃO."
        ),
        TipoResultado.CONSULTA_CANCELADA: (
            "Pronto! Sua consulta foi desmarcada.\nO horário ficou livre para outra pessoa."
        ),
        TipoResultado.CONSULTA_NAO_ENCONTRADA: (
            "Não achei consulta marcada {periodo}.\nPara ver suas consultas, escreva: MINHAS CONSULTAS."
        ),
        TipoResultado.CANCELAMENTO_AMBIGUO: (
            "Você tem mais de uma consulta:\n{lista}\nEscreva o dia e a hora da consulta que quer desmarcar."
        ),
        TipoResultado.LISTA_CONSULTAS: "Suas próximas consultas:\n{lista}",
        TipoResultado.SEM_CONSULTAS: (
            "Você não tem consultas marcadas.\nPara marcar, escreva: MARCAR CONSULTA."
        ),
        TipoResultado.AGENDAMENTO_DESCARTADO: "Tudo bem. Não marquei nada.\nPosso ajudar em algo mais?",
        TipoResultado.CANCELAMENTO_DESCARTADO: "Tudo bem. Sua consulta continua marcada.",
        TipoResultado.ORIENTAR_REMARCACAO: (
            "Para trocar o dia da consulta:\n1. Primeiro, desmarque a consulta antiga.\n"
            "2. Depois, marque uma nova.\nExemplo: \"desmarcar consulta do dia 20\"."
        ),
        TipoResultado.REGRA_VIOLADA: "{detalhe}",
        TipoResultado.SAUDACAO: (
            "Olá! Eu ajudo a marcar consultas.\nO que você quer fazer?\n"
            "1. Marcar consulta.\n2. Ver minhas consultas.\n3. Desmarcar consulta."
        ),
        TipoResultado.AGRADECIMENTO: "De nada! Estou aqui se precisar.",
        TipoResultado.AJUDA: (
            "Desculpe, não entendi.\nVocê pode escrever assim:\n"
            "1. \"Quero marcar consulta com médico do coração.\"\n2. \"Minhas consultas.\"\n"
            "3. \"Desmarcar consulta do dia 20.\""
        ),
        TipoResultado.PACIENTE_NAO_CADASTRADO: (
            "Não achei seu cadastro de paciente.\nPor favor, fale com a recepção da clínica."
        ),
    }

    def describe_when(self, opcao: OpcaoAgenda) -> str:
        return f"Dia: {self._data_por_extenso(opcao.data)}.\nHorário: {self._hora_por_extenso(opcao.hora)}."

    def describe_specialty(self, especialidade: str) -> str:
        return termo_leigo(especialidade) if especialidade else "médico"

    def describe_list(self, opcoes: Sequence[OpcaoAgenda]) -> str:
        return "\n".join(
            f"{posicao}. {self._data_por_extenso(opcao.data)}, {self._hora_por_extenso(opcao.hora)}, com {opcao.medico}."
            for posicao, opcao in enumerate(opcoes, start=1)
        )

    def describe_doctors(self, medicos: Sequence[str]) -> str:
        return "\n".join(f"{posicao}. {medico}" for posicao, medico in enumerate(medicos, start=1))

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

    @staticmethod
    def _data_por_extenso(data: date) -> str:
        return f"{DIAS_DA_SEMANA[data.weekday()]}, {data.day} de {MESES[data.month - 1]}"

    @staticmethod
    def _hora_por_extenso(hora: str) -> str:
        horas, minutos = (int(parte) for parte in hora.split(":"))
        if minutos:
            return f"às {horas}h{minutos:02d}"
        return "à 1 hora" if horas == 1 else f"às {horas} horas"


class StandardStyle(ResponseStyle):
    nome = "padrao"
    avisos = {
        Aviso.HORARIO_RESERVADO: "Este horário acabou de ser reservado por outro paciente. ",
        Aviso.HORARIO_PEDIDO_INDISPONIVEL: "O horário solicitado não está disponível. ",
    }
    modelos = {
        TipoResultado.CONSULTA_AGENDADA: (
            "Consulta agendada com {medico} ({especialidade}) em {quando}. "
            "Ela já aparece em \"Meus Agendamentos\"."
        ),
        TipoResultado.SUGESTAO_HORARIO: (
            "{aviso}Próximo horário disponível em {especialidade}: {medico}, {quando}. "
            "Responda \"sim\" para agendar, \"outro\" para ver a próxima opção ou \"não\" para cancelar."
        ),
        TipoResultado.HORARIO_RESERVADO: (
            "Este horário acabou de ser reservado por outro paciente. "
            "Não encontrei outra opção com os mesmos critérios; informe outra data ou período."
        ),
        TipoResultado.SEM_HORARIOS: (
            "Não há horários disponíveis em {especialidade} {periodo}. Tente outra data ou período."
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
            "Responda \"sim\" para confirmar ou \"não\" para manter."
        ),
        TipoResultado.CONSULTA_CANCELADA: "Consulta com {medico} em {quando} cancelada. O horário foi liberado.",
        TipoResultado.CONSULTA_NAO_ENCONTRADA: "Não encontrei consulta agendada {periodo}.",
        TipoResultado.CANCELAMENTO_AMBIGUO: (
            "Você possui mais de uma consulta nesse critério:\n{lista}\nInforme a data e o horário da que deseja cancelar."
        ),
        TipoResultado.LISTA_CONSULTAS: "Suas próximas consultas:\n{lista}",
        TipoResultado.SEM_CONSULTAS: "Você não possui consultas agendadas.",
        TipoResultado.AGENDAMENTO_DESCARTADO: "Ok, nenhum agendamento foi feito.",
        TipoResultado.CANCELAMENTO_DESCARTADO: "Ok, a consulta foi mantida.",
        TipoResultado.ORIENTAR_REMARCACAO: (
            "Para remarcar, cancele a consulta atual (ex.: \"cancelar consulta do dia 12/11\") "
            "e depois agende o novo horário."
        ),
        TipoResultado.REGRA_VIOLADA: "{detalhe}",
        TipoResultado.SAUDACAO: "Olá! Posso agendar, listar ou cancelar consultas. Como posso ajudar?",
        TipoResultado.AGRADECIMENTO: "Por nada! Precisando, é só chamar.",
        TipoResultado.AJUDA: (
            "Não entendi a solicitação. Exemplos: \"agendar cardiologia amanhã às 10h\", "
            "\"minhas consultas\", \"cancelar consulta do dia 25/10\"."
        ),
        TipoResultado.PACIENTE_NAO_CADASTRADO: (
            "Não há cadastro de paciente vinculado ao seu usuário. Procure a recepção para concluir o cadastro."
        ),
    }

    def describe_when(self, opcao: OpcaoAgenda) -> str:
        return f"{opcao.data:%d/%m/%Y} ({DIAS_DA_SEMANA[opcao.data.weekday()]}) às {opcao.hora}"

    def describe_specialty(self, especialidade: str) -> str:
        return especialidade

    def describe_list(self, opcoes: Sequence[OpcaoAgenda]) -> str:
        return "\n".join(
            f"• {opcao.data:%d/%m/%Y} às {opcao.hora} — {opcao.medico} ({opcao.especialidade})" for opcao in opcoes
        )

    def describe_doctors(self, medicos: Sequence[str]) -> str:
        return ", ".join(medicos)

    def describe_period(self, periodo: IntervaloDatas | None) -> str:
        if periodo is None:
            return "no período informado"
        if periodo.inicio == periodo.fim:
            return f"em {periodo.inicio:%d/%m/%Y}"
        return f"entre {periodo.inicio:%d/%m/%Y} e {periodo.fim:%d/%m/%Y}"


class ResponseDecisionTree:
    def __init__(self) -> None:
        self._estilos: dict[PerfilEtario, ResponseStyle] = {
            PerfilEtario.IDOSO: SimplifiedStyle(),
            PerfilEtario.PADRAO: StandardStyle(),
        }

    def choose_style(self, perfil: PerfilEtario) -> ResponseStyle:
        return self._estilos[perfil]

    def respond(self, perfil: PerfilEtario, resultado: ResultadoDialogo) -> str:
        return self.choose_style(perfil).write(resultado)
