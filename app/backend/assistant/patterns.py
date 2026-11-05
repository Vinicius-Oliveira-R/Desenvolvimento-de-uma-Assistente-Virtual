from typing import Any

from app.backend.assistant.especialidades import (
    ARTIGOS,
    CATALOGO,
    CONECTIVOS_LEIGOS,
    EXPRESSOES_SEM_PREFERENCIA,
    PROFISSIONAIS,
    SINTOMAS_E_TERMOS_COLOQUIAIS,
)
from app.backend.core.text import normalizar

Padrao = list[dict[str, Any]]

TITULOS_MEDICOS = ("dr", "dr.", "dra", "dra.", "doutor", "doutora")
DIAS_DA_SEMANA = ("segunda", "terca", "quarta", "quinta", "sexta", "sabado", "domingo")
PREPOSICOES_TURNO = ("de", "pela", "na", "a", "da")
UNIDADES_HORA = ("h", "hs", "hrs", "hora", "horas")

PALAVRAS_FORA_DE_NOME = (
    "a", "o", "e", "as", "ao", "aos", "de", "do", "da", "dos", "das", "em", "no", "na", "para", "pra", "pro",
    "com", "por", "pelo", "pela", "que", "q", "se", "ou", "ate", "mas", "me", "mim", "minha", "meu", "um", "uma",
    "dia", "dias", "hoje", "amanha", "depois", "semana", "mes", "proxima", "proximo", "agora", "cedo", "tarde",
    "noite", "manha", "hora", "horas", "h", "feira", "consulta", "consultas", "favor", "sim", "nao", "ja",
    "pode", "quero", "queria", "gostaria", "preciso", "obrigado", "obrigada", "retorno", "exame", "aqui", "la",
    *DIAS_DA_SEMANA,
    *(termo for especialidade in CATALOGO for termo in especialidade.termos_tecnicos if " " not in termo),
)

SINAL_AFIRMACAO = "AFIRMACAO"
SINAL_AFIRMACAO_INICIAL = "AFIRMACAO_INICIAL"
SINAL_NEGACAO = "NEGACAO"
SINAL_OUTRA_OPCAO = "OUTRA_OPCAO"
SINAL_MENCAO_CONSULTA = "MENCAO_CONSULTA"
SINAL_SEM_PREFERENCIA = "SEM_PREFERENCIA"


def _termo(texto: str) -> Padrao:
    return [{"NORM": parte} for parte in normalizar(texto).split()]


def _alguma(*palavras: str) -> dict[str, Any]:
    return {"NORM": {"IN": list(palavras)}}


def padroes_entidades() -> list[dict[str, Any]]:
    padroes: list[dict[str, Any]] = []
    for especialidade in CATALOGO:
        for termo in especialidade.termos_tecnicos:
            padroes.append({"label": "ESPECIALIDADE", "id": especialidade.nome, "pattern": _termo(termo)})
        if especialidade.orgaos:
            padroes.append({
                "label": "ESPECIALIDADE",
                "id": especialidade.nome,
                "pattern": [
                    _alguma(*PROFISSIONAIS),
                    _alguma(*CONECTIVOS_LEIGOS),
                    {**_alguma(*ARTIGOS), "OP": "?"},
                    _alguma(*especialidade.orgaos),
                ],
            })
    for especialidade, termos in SINTOMAS_E_TERMOS_COLOQUIAIS.items():
        for termo in termos:
            padroes.append({"label": "ESPECIALIDADE_INFERIDA", "id": especialidade, "pattern": _termo(termo)})

    padroes.append({
        "label": "MEDICO",
        "pattern": [
            _alguma(*TITULOS_MEDICOS),
            {"ORTH": ".", "OP": "?"},
            {"IS_ALPHA": True, "NORM": {"NOT_IN": list(PALAVRAS_FORA_DE_NOME)}, "OP": "{1,3}"},
        ],
    })

    padroes += [
        {"label": "DATA", "id": "explicita", "pattern": [{"TEXT": {"REGEX": r"^\d{1,2}/\d{1,2}(/\d{2}|/\d{4})?$"}}]},
        {"label": "DATA", "id": "explicita", "pattern": [{"TEXT": {"REGEX": r"^\d{4}-\d{2}-\d{2}$"}}]},
        {"label": "DATA", "id": "hoje", "pattern": _termo("hoje")},
        {"label": "DATA", "id": "amanha", "pattern": _termo("amanha")},
        {"label": "DATA", "id": "depois_de_amanha", "pattern": _termo("depois de amanha")},
        {"label": "DATA", "id": "dia_do_mes", "pattern": [{"NORM": "dia"}, {"TEXT": {"REGEX": r"^\d{1,2}$"}}]},
        {"label": "PERIODO", "id": "proxima_semana", "pattern": [{"NORM": "semana"}, _alguma("que", "q"), {"NORM": "vem"}]},
        {"label": "PERIODO", "id": "proxima_semana", "pattern": [_alguma("proxima", "prox"), {"NORM": "semana"}]},
        {"label": "PERIODO", "id": "esta_semana", "pattern": [_alguma("esta", "essa", "nesta", "nessa"), {"NORM": "semana"}]},
        {"label": "PERIODO", "id": "proximo_mes", "pattern": [{"NORM": "mes"}, _alguma("que", "q"), {"NORM": "vem"}]},
        {"label": "PERIODO", "id": "proximo_mes", "pattern": [_alguma("proximo", "prox"), {"NORM": "mes"}]},
        {"label": "HORA", "pattern": [{"TEXT": {"REGEX": r"^\d{1,2}h(\d{2})?$"}}]},
        {"label": "HORA", "pattern": [{"TEXT": {"REGEX": r"^\d{1,2}:\d{2}$"}}]},
        {
            "label": "HORA",
            "pattern": [_alguma("as", "a"), {"TEXT": {"REGEX": r"^\d{1,2}$"}}, {**_alguma(*UNIDADES_HORA), "OP": "?"}],
        },
        {"label": "HORA", "pattern": [{"TEXT": {"REGEX": r"^\d{1,2}$"}}, _alguma(*UNIDADES_HORA)]},
        {"label": "HORA", "pattern": [{"NORM": "meio"}, {"ORTH": "-", "OP": "?"}, {"NORM": "dia"}]},
        {"label": "HORA", "pattern": [{"NORM": "meio-dia"}]},
    ]
    for turno in ("manha", "tarde", "noite"):
        padroes.append({"label": "TURNO", "id": turno, "pattern": [_alguma(*PREPOSICOES_TURNO), {"NORM": turno}]})
    for indice, dia in enumerate(DIAS_DA_SEMANA):
        padroes.append({
            "label": "DIA_SEMANA",
            "id": str(indice),
            "pattern": [_alguma(dia, f"{dia}-feira"), {"ORTH": "-", "OP": "?"}, {"NORM": "feira", "OP": "?"}],
        })
    return padroes


PADROES_SINAIS: dict[str, list[Padrao]] = {
    "cancelar": [[_alguma(
        "cancelar", "cancela", "cancele", "cancelo", "cancelamento",
        "desmarcar", "desmarca", "desmarque", "desmarco",
    )]],
    "remarcar": [
        [_alguma("remarcar", "remarca", "remarque", "reagendar", "reagenda", "reagende", "remarcacao", "reagendamento")],
        [
            _alguma("trocar", "troca", "mudar", "muda", "alterar", "altera"),
            {**_alguma("o", "a", "de", "da", "do"), "OP": "?"},
            _alguma("dia", "data", "horario", "hora"),
        ],
    ],
    "agendar": [
        [_alguma("agendar", "agenda", "agende", "agendo", "agendamento", "marcar", "marca", "marque", "marco", "marcacao")],
        [_alguma("tem", "tera", "existe", "ha", "algum", "alguma"), _alguma("horario", "horarios", "vaga", "vagas")],
        [_alguma("melhor", "proximo", "primeiro"), _alguma("horario", "horarios", "vaga", "dia")],
        [_alguma("horario", "horarios"), _alguma("disponivel", "disponiveis", "livre", "livres")],
    ],
    "listar": [
        [_alguma("minha", "minhas", "meu", "meus"), _alguma("consulta", "consultas", "agendamento", "agendamentos")],
        [
            _alguma("ver", "listar", "mostrar", "mostra", "quais"),
            {**_alguma("sao", "as", "os", "minhas", "meus", "todas"), "OP": "*"},
            _alguma("consultas", "agendamentos"),
        ],
    ],
    "saudacao": [[_alguma("oi", "ola", "opa")], [_alguma("bom", "boa"), _alguma("dia", "tarde", "noite")]],
    "agradecimento": [[_alguma("obrigado", "obrigada", "obg", "valeu", "agradeco", "grato", "grata", "brigado", "brigada")]],
    SINAL_AFIRMACAO: [[_alguma(
        "sim", "s", "confirmo", "confirmar", "confirma", "confirmado", "ok", "okay", "certo", "isso", "claro",
        "perfeito", "beleza", "blz", "aceito", "positivo", "combinado", "fechado", "otimo",
    )]],
    SINAL_AFIRMACAO_INICIAL: [[_alguma("pode", "quero", "bora")]],
    SINAL_NEGACAO: [[_alguma("nao", "n", "negativo", "desisto", "deixa")]],
    SINAL_OUTRA_OPCAO: [
        [_alguma("outro", "outra", "outros", "outras")],
        [_alguma("proximo", "proxima"), _alguma("horario", "opcao", "vaga")],
    ],
    SINAL_MENCAO_CONSULTA: [[_alguma("consulta", "medico", "medica", "doutor", "doutora")]],
    SINAL_SEM_PREFERENCIA: [_termo(expressao) for expressao in EXPRESSOES_SEM_PREFERENCIA],
}
