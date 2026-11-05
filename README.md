# Assistente Clínico

## Descrição

Protótipo de sistema para agendamento e gestão de consultas clínicas com assistente virtual em linguagem natural, que adapta a linguagem da resposta ao perfil etário inferido do paciente.

## Objetivo

Implementar uma API robusta em Python com FastAPI, banco relacional PostgreSQL e módulos de NLP/ML para apoiar o agendamento de consultas, gestão de disponibilidade e adaptação da comunicação, com um front-end Django (SSR + HTMX).

## Tecnologias

- Python 3.11+
- Back-end: FastAPI, SQLAlchemy, Pydantic, PostgreSQL, bcrypt, JWT
- NLP/ML: spaCy (pipeline `pt` com EntityRuler e Matcher), scikit-learn (Random Forest)
- Front-end: Django, HTMX, Alpine.js, Bootstrap 5, httpx
- Testes: pytest e Django TestCase

## Arquitetura

```text
assistente-clinico/
├── app/
│   ├── backend/                 # API FastAPI
│   │   ├── core/                # configuração, banco, segurança, exceções de domínio, relógio
│   │   ├── models/              # entidades do domínio
│   │   ├── schemas/             # validação de entrada e saída
│   │   ├── repositories/        # persistência (inclui SELECT ... FOR UPDATE)
│   │   ├── services/            # regras de negócio (agendamento atômico, agenda)
│   │   ├── routers/             # endpoints da API (prefixo /api)
│   │   ├── assistant/           # NLP com spaCy, diálogo e árvore de decisão das respostas
│   │   ├── ml/                  # heurísticas de Nielsen, Random Forest e corpus de treino
│   │   ├── tests/
│   │   └── seed.py              # dados de demonstração
│   └── frontend/                # Django (SSR) consumindo a API via httpx
├── scripts/e2e_smoke.py         # teste E2E com os dois servidores em execução
└── docs/
```

Pipeline do assistente (`POST /api/assistant/chat`):

1. **spaCy** extrai intenção (Matcher) e entidades (EntityRuler): especialidade, médico, data, período, hora e turno. Quando o paciente descreve um sintoma ou usa um termo popular ("dor nas costas", "consulta do coração"), a especialidade é inferida pelo dicionário `SINTOMAS_E_TERMOS_COLOQUIAIS`.
2. **Heurísticas de Nielsen** transformam a mensagem em um vetor numérico (taxa de erros, complexidade, hesitação, vagueza e informalidade).
3. **Random Forest** prevê o perfil etário (`IDOSO` ou `PADRAO`), suavizado ao longo da conversa. A conversa começa no estilo simplificado e só muda quando há evidência suficiente, porque mensagens curtas pesam pouco.
4. **Gerenciador de diálogo** agenda, sugere horários, lista ou cancela (cancelamento exige confirmação). A especialidade é perguntada no máximo uma vez: se o paciente não souber ("não sei", "qualquer um"), o agendamento segue com Clínica Geral. Pedidos de remédio, receita ou diagnóstico são recusados, porque o sistema não diagnostica nem prescreve, e viram uma oferta de consulta com Clínica Geral.
5. **Árvore de decisão** escolhe o estilo da resposta: linguagem simplificada, sem termos técnicos e com passos numerados para `IDOSO`.

## Perfis de acesso (RBAC)

Cada usuário tem um `papel`: `gestor` (responsável pela clínica), `admin` (atendente), `medico` ou `paciente`. O papel é conferido no banco a cada requisição, a partir do usuário identificado pelo token JWT.

| Usuário logado | Cadastra usuários (`POST /api/auth/register`) | Pacientes (`POST`/`GET /api/pacientes`) | Médicos (`POST /api/medicos`) | Consultas (`/api/consultas`) |
|---|---|---|---|---|
| `gestor` | médicos e atendentes | não | sim | não |
| `admin` | pacientes e atendentes | sim | não | agenda, remarca e cancela |
| `medico` | pacientes, atendentes e médicos | sim | sim | agenda, remarca e cancela |
| `paciente` | não | não | não | só as próprias (`/api/consultas/minhas`) e pelo assistente |

Ninguém cadastra um `gestor` pela API, nem outro gestor: essa conta só é criada direto no banco, pelo seed. As permissões de cadastro ficam em um único lugar, `PAPEIS_CADASTRAVEIS` em `app/backend/models/usuario.py`.

O cadastro de um paciente tem duas etapas: `POST /api/auth/register` cria o usuário (com o `papel`) e `POST /api/pacientes` cria a ficha vinculada a ele (`usuario_id`). Sem token, essas rotas respondem 401; com um perfil sem permissão, 403.

## Instalação

```bash
python -m venv .venv
.venv\Scripts\activate
pip install -r app/backend/requirements.txt -r app/frontend/requirements.txt
```

## Configuração

Copie `app/backend/.env.example` para `app/backend/.env` e ajuste as variáveis (o arquivo é lido independentemente do diretório de execução).

O front-end lê variáveis de ambiente opcionais: `FASTAPI_BASE_URL` (padrão `http://127.0.0.1:8000/api`), `DJANGO_SECRET_KEY`, `DJANGO_DEBUG` e `DJANGO_ALLOWED_HOSTS`.

### Banco já existente

O `create_all` não altera tabelas que já existem. Em um banco SQLite de demonstração, basta apagar o arquivo e rodar o seed. Em um PostgreSQL criado por versões anteriores, execute o SQL do seu caso e depois rode o seed, que cria os usuários de gestor, atendente e médico.

Banco criado antes dos perfis de acesso (a tabela `usuarios` ainda tem a coluna `tipo`):

```sql
ALTER TABLE consultas DROP CONSTRAINT IF EXISTS uq_consulta_medico_horario_status;
CREATE UNIQUE INDEX IF NOT EXISTS uq_consulta_horario_ativa ON consultas (horario_id) WHERE status <> 'cancelada';
ALTER TABLE usuarios RENAME COLUMN tipo TO papel;
UPDATE usuarios SET papel = 'paciente' WHERE papel NOT IN ('admin', 'medico', 'paciente');
```

Qualquer banco criado antes do papel `gestor` (inclusive depois do SQL acima):

```sql
ALTER TABLE usuarios DROP CONSTRAINT IF EXISTS papelusuario;
ALTER TABLE usuarios ADD CONSTRAINT papelusuario CHECK (papel IN ('gestor', 'admin', 'medico', 'paciente'));
```

## Execução

Na raiz do projeto:

```bash
python -m app.backend.seed                      # dados de demonstração (idempotente)
uvicorn app.backend.main:app --reload           # API em http://127.0.0.1:8000 (docs em /docs)
```

Em outro terminal:

```bash
cd app/frontend
python manage.py migrate
python manage.py runserver 8001                 # front-end em http://127.0.0.1:8001
```

Usuários de demonstração (senha `senha123`): `gestor@clinica.com` (`gestor`), `recepcao@clinica.com` (atendente, `admin`), `joao.mendes@clinica.com` (`medico`), `lurdes@clinica.com` e `carlos@clinica.com` (`paciente`). No site Django, pacientes caem no chat; gestor, atendentes e médicos caem no painel da equipe, onde cadastram usuários (com a ficha de paciente ou de médico) e, conforme o perfil, consultam a lista de pacientes. Atendentes e médicos também gerenciam as consultas: agenda com filtros, novo agendamento, remarcação e cancelamento (alterações e cancelamentos exigem marcar que o paciente confirmou).

## Testes

```bash
pytest                                          # back-end, incluindo os cenários E2E via API
cd app/frontend && python manage.py test assistant
python scripts/e2e_smoke.py                     # E2E real (exige API e front-end em execução)
python -m app.backend.ml.train                  # validação cruzada do Random Forest
```

O teste de concorrência em PostgreSQL real roda quando `TEST_POSTGRES_URL` aponta para um banco **descartável** (as tabelas são recriadas):

```bash
set TEST_POSTGRES_URL=postgresql+psycopg://postgres:postgres@localhost:5432/assistente_clinico_test
pytest -k postgresql
```
