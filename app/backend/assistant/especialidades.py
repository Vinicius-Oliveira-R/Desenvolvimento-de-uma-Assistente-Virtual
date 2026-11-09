from dataclasses import dataclass

from app.backend.core.text import normalizar

PROFISSIONAIS = ("medico", "medica", "doutor", "doutora")
CONECTIVOS_LEIGOS = ("do", "da", "dos", "das", "de", "pra", "pro", "pros", "para")
ARTIGOS = ("o", "a", "os", "as")


@dataclass(frozen=True)
class Especialidade:
    nome: str
    termos_tecnicos: tuple[str, ...]
    termo_leigo: str
    orgaos: tuple[str, ...] = ()

    def corresponde_a(self, especialidade_cadastrada: str) -> bool:
        return normalizar(especialidade_cadastrada) == normalizar(self.nome)


CATALOGO: tuple[Especialidade, ...] = (
    Especialidade(
        "Cardiologia",
        ("cardiologia", "cardiologista", "cardio", "cardiologico", "cardiologica"),
        "médico do coração",
        ("coracao",),
    ),
    Especialidade(
        "Dermatologia",
        ("dermatologia", "dermatologista", "dermato"),
        "médico da pele",
        ("pele",),
    ),
    Especialidade(
        "Ortopedia",
        ("ortopedia", "ortopedista"),
        "médico dos ossos",
        ("ossos", "osso", "coluna", "joelho"),
    ),
    Especialidade(
        "Neurologia",
        ("neurologia", "neurologista", "neuro"),
        "médico dos nervos e da memória",
    ),
    Especialidade(
        "Pediatria",
        ("pediatria", "pediatra"),
        "médico das crianças",
        ("crianca", "criancas"),
    ),
    Especialidade(
        "Ginecologia",
        ("ginecologia", "ginecologista", "gineco"),
        "médico da saúde da mulher",
        ("mulher",),
    ),
    Especialidade(
        "Oftalmologia",
        ("oftalmologia", "oftalmologista", "oftalmo", "oculista"),
        "médico dos olhos",
        ("olhos", "olho", "vista"),
    ),
    Especialidade(
        "Clínica Geral",
        ("clinico geral", "clinica geral", "clinico"),
        "clínico geral",
    ),
    Especialidade(
        "Endocrinologia",
        ("endocrinologia", "endocrinologista", "endocrino"),
        "médico dos hormônios",
    ),
    Especialidade(
        "Psiquiatria",
        ("psiquiatria", "psiquiatra"),
        "médico da saúde mental",
    ),
    Especialidade(
        "Otorrinolaringologia",
        ("otorrinolaringologia", "otorrinolaringologista", "otorrino"),
        "médico de ouvido, nariz e garganta",
        ("ouvido", "nariz", "garganta"),
    ),
)

ESPECIALIDADE_PADRAO = "Clínica Geral"

SINTOMAS_E_TERMOS_COLOQUIAIS: dict[str, tuple[str, ...]] = {
    "Cardiologia": ("coração", "pressão", "palpitação", "batedeira", "colesterol", "arritmia"),
    "Dermatologia": (
        "pele", "mancha na pele", "manchas na pele", "coceira", "espinha", "espinhas", "acne", "verruga",
        "queda de cabelo", "cabelo caindo", "caspa", "micose", "unha",
    ),
    "Ortopedia": (
        "dor nas costas", "dor na costa", "costas", "coluna", "osso", "ossos", "joelho", "joelhos", "ombro",
        "quadril", "tornozelo", "juntas", "dor na junta", "fratura", "torci", "torção",
    ),
    "Neurologia": (
        "dor de cabeça", "dor na cabeça", "enxaqueca", "memória", "esquecimento", "esquecendo", "formigamento",
        "tremor", "tremedeira",
    ),
    "Pediatria": ("criança", "crianças", "nenê", "neném"),
    "Ginecologia": ("preventivo", "papanicolau", "menstruação", "gravidez", "grávida", "menopausa"),
    "Oftalmologia": ("vista", "olho", "olhos", "visão", "enxergar", "enxergando", "óculos", "catarata", "glaucoma"),
    "Endocrinologia": ("diabetes", "diabete", "açúcar", "glicose", "tireoide", "hormônio", "hormônios"),
    "Psiquiatria": ("ansiedade", "depressão", "insônia", "pânico"),
    "Otorrinolaringologia": ("ouvido", "ouvidos", "nariz", "garganta", "zumbido", "sinusite", "rinite", "surdez"),
    ESPECIALIDADE_PADRAO: (
        "médico geral", "médica geral", "consulta geral", "médico de família", "médica de família",
        "check-up", "check up", "checkup", "de rotina", "febre", "gripe", "resfriado", "tontura", "cansaço",
        "mal-estar", "mal estar", "barriga", "estômago",
    ),
}

EXPRESSOES_SEM_PREFERENCIA = (
    "não sei", "n sei", "nem sei", "sei lá", "não faço ideia", "tanto faz", "geral", "você escolhe", "vc escolhe",
    "qualquer um", "qualquer uma", "qualquer médico", "qualquer médica", "qualquer doutor", "qualquer doutora",
    "qualquer especialidade", "qualquer especialista",
)

_POR_NOME = {normalizar(especialidade.nome): especialidade for especialidade in CATALOGO}


def buscar_especialidade(nome: str) -> Especialidade | None:
    return _POR_NOME.get(normalizar(nome))


def termo_leigo(nome: str) -> str:
    especialidade = buscar_especialidade(nome)
    return especialidade.termo_leigo if especialidade else nome.lower()
