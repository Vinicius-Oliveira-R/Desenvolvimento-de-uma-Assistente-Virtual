"""Teste E2E de fumaça: simula pacientes reais usando o front-end Django, que conversa com a API FastAPI.

Pré-requisitos (veja o README): API em execução (uvicorn), front-end em execução (runserver)
e banco populado com `python -m app.backend.seed`. O script desfaz os agendamentos que cria.

Uso: python scripts/e2e_smoke.py [--frontend http://127.0.0.1:8001] [--api http://127.0.0.1:8000/api]
"""

import argparse
import html
import re
import sys
import threading
from datetime import date

import httpx

MENSAGEM_RESERVADO = "Este horário acabou de ser reservado por outro paciente."
SENHA_DEMO = "senha123"
ATENDENTE_DEMO = "recepcao@clinica.com"
_CSRF = re.compile(r'name="csrfmiddlewaretoken" value="([^"]+)"')


class FalhaE2E(AssertionError):
    pass


def verificar(condicao: bool, descricao: str) -> None:
    print(f"  [{'OK' if condicao else 'FALHA'}] {descricao}")
    if not condicao:
        raise FalhaE2E(descricao)


def proxima_ocorrencia(dia: int, mes: int) -> date:
    hoje = date.today()
    alvo = date(hoje.year, mes, dia)
    return alvo if alvo >= hoje else alvo.replace(year=hoje.year + 1)


class PacienteNoNavegador:
    def __init__(self, frontend: str, email: str):
        self.email = email
        self.http = httpx.Client(base_url=frontend, follow_redirects=True, timeout=30)
        pagina_login = self.http.get("/login/")
        chat = self.http.post(
            "/login/",
            data={"username": email, "password": SENHA_DEMO, "csrfmiddlewaretoken": self._csrf(pagina_login.text)},
        )
        verificar(chat.url.path == "/", f"{email} faz login e chega ao chat")
        self._csrf_token = self._csrf(chat.text)

    def enviar(self, mensagem: str) -> str:
        resposta = self.http.post(
            "/", data={"message": mensagem, "csrfmiddlewaretoken": self._csrf_token}, headers={"HX-Request": "true"}
        )
        verificar(resposta.status_code == 200, f"POST HTMX \"{mensagem}\" retorna o fragmento HTML")
        texto = self._texto_do_assistente(resposta.text)
        print("    > " + texto.replace("\n", "\n      "))
        return texto

    def calendario(self) -> str:
        return self.http.get("/calendario/").text

    @staticmethod
    def _csrf(pagina: str) -> str:
        return _CSRF.search(pagina).group(1)

    @staticmethod
    def _texto_do_assistente(fragmento: str) -> str:
        bolha = fragmento.split('class="chat-bubble assistant">', 1)[1]
        bolha = re.sub(r"<br\s*/?>", "\n", bolha)
        linhas = (html.unescape(re.sub(r"<[^>]+>", "", linha)).strip() for linha in bolha.splitlines())
        return "\n".join(linha for linha in linhas if linha)


def autenticar_atendente(api: httpx.Client) -> None:
    sessao = api.post("/auth/login", json={"email": ATENDENTE_DEMO, "senha": SENHA_DEMO})
    verificar(sessao.status_code == 200, f"{ATENDENTE_DEMO} (atendente) faz login na API")
    api.headers["Authorization"] = f"Bearer {sessao.json()['token']}"


def cenario_a(frontend: str) -> None:
    print("\nCenário A - paciente idoso (adaptação de linguagem)")
    lurdes = PacienteNoNavegador(frontend, "lurdes@clinica.com")

    sugestao = lurdes.enviar("queria marca consulta com cardiologista pra semana q vem se der...")
    verificar("Perfil: IDOSO" in sugestao, "Random Forest classifica o perfil como IDOSO")
    verificar("médico do coração" in sugestao and "cardiolog" not in sugestao.lower(), "resposta sem termos técnicos")
    verificar("1. Para marcar, escreva SIM." in sugestao, "orientação passo a passo")

    verificar("Pronto! Sua consulta está marcada." in lurdes.enviar("sim"), "consulta agendada após confirmação")
    verificar("Dr. João Mendes" in lurdes.calendario(), "consulta visível em /calendario/")

    verificar("Você quer desmarcar esta consulta?" in lurdes.enviar("quero desmarcar minha consulta"), "pede confirmação")
    verificar("Pronto! Sua consulta foi desmarcada." in lurdes.enviar("sim"), "consulta desmarcada (limpeza)")


def cenario_b(frontend: str, api: httpx.Client) -> None:
    print("\nCenário B - paciente padrão (agendamento completo e cancelamento)")
    carlos = PacienteNoNavegador(frontend, "carlos@clinica.com")
    alvo = proxima_ocorrencia(25, 10)
    dra_maria = next(medico for medico in api.get("/medicos").json() if medico["nome"] == "Dra. Maria Silva")

    def horario_disponivel() -> bool:
        return next(
            h["disponivel"]
            for h in api.get("/horarios").json()
            if h["medico_id"] == dra_maria["id"] and h["data"] == alvo.isoformat() and h["hora_inicio"] == "14:00"
        )

    agendamento = carlos.enviar("Quero agendar consulta com Dra. Maria dia 25/10 às 14h")
    verificar("Perfil: PADRAO" in agendamento, "perfil classificado como PADRAO")
    verificar("Consulta agendada com Dra. Maria Silva" in agendamento, "consulta cadastrada")
    verificar(f"{alvo:%d/%m/%Y}" in carlos.calendario(), f"consulta de {alvo:%d/%m/%Y} visível em /calendario/")
    verificar(not horario_disponivel(), "horário marcado como ocupado no banco")

    verificar("Confirma o cancelamento" in carlos.enviar("Cancelar minha consulta do dia 25/10"), "pede confirmação")
    verificar("O horário foi liberado." in carlos.enviar("sim"), "consulta cancelada")
    verificar(horario_disponivel(), "horário liberado no banco")


def cenario_c(api_url: str, api: httpx.Client) -> None:
    print("\nCenário C - concorrência (duas reservas simultâneas do mesmo horário)")
    pacientes = api.get("/pacientes").json()[:2]
    horario = [h for h in api.get("/horarios").json() if h["disponivel"]][-1]
    largada = threading.Barrier(len(pacientes))
    respostas: list[httpx.Response] = []

    def reservar(paciente: dict) -> None:
        with httpx.Client(base_url=api_url, timeout=30) as cliente:
            largada.wait()
            respostas.append(
                cliente.post(
                    "/consultas",
                    json={
                        "paciente_id": paciente["id"],
                        "medico_id": horario["medico_id"],
                        "horario_id": horario["id"],
                        "data": horario["data"],
                    },
                )
            )

    threads = [threading.Thread(target=reservar, args=(paciente,)) for paciente in pacientes]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    verificar(sorted(r.status_code for r in respostas) == [201, 409], "uma reserva confirmada (201) e uma recusada (409)")
    recusada = next(r for r in respostas if r.status_code == 409)
    verificar(recusada.json()["detail"] == MENSAGEM_RESERVADO, f"mensagem amigável: \"{MENSAGEM_RESERVADO}\"")

    criada = next(r for r in respostas if r.status_code == 201).json()
    api.request("DELETE", f"/consultas/{criada['id']}", json={"confirmado": True}).raise_for_status()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--frontend", default="http://127.0.0.1:8001")
    parser.add_argument("--api", default="http://127.0.0.1:8000/api")
    args = parser.parse_args()

    with httpx.Client(base_url=args.api, timeout=30) as api:
        try:
            autenticar_atendente(api)
            cenario_a(args.frontend)
            cenario_b(args.frontend, api)
            cenario_c(args.api, api)
        except FalhaE2E:
            print("\nE2E: FALHOU")
            return 1
    print("\nE2E: todos os cenários passaram")
    return 0


if __name__ == "__main__":
    sys.exit(main())
