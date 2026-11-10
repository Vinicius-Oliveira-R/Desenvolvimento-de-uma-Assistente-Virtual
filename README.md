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

| Usuário logado | Cadastra usuários (`POST /api/auth/register`) | Pacientes (`POST`/`GET /api/pacientes`) | Médicos (`POST /api/medicos`) | Consultas (`/api/consultas`) | Horários (`POST /api/horarios` e `/lote`) |
|---|---|---|---|---|---|
| `gestor` | médicos e atendentes | não | sim | não | não |
| `admin` | pacientes e atendentes | sim | não | agenda, remarca e cancela | libera |
| `medico` | pacientes, atendentes e médicos | sim | sim | agenda, remarca e cancela | libera |
| `paciente` | não | não | não | só as próprias (`/api/consultas/minhas`) e pelo assistente | não |

Ninguém cadastra um `gestor` pela API, nem outro gestor: essa conta só é criada direto no banco, pelo seed. As permissões de cadastro ficam em um único lugar, `PAPEIS_CADASTRAVEIS` em `app/backend/models/usuario.py`.

O cadastro de um paciente tem duas etapas: `POST /api/auth/register` cria o usuário (com o `papel`) e `POST /api/pacientes` cria a ficha vinculada a ele (`usuario_id`). Sem token, essas rotas respondem 401; com um perfil sem permissão, 403.

## Pedidos de remarcação e cancelamento

Toda remarcação ou cancelamento pede confirmação de quem solicita ("Tem certeza?" na tela da equipe; "sim" no chat do paciente).

- Quando a atendente ou o médico remarca ou cancela, por padrão a consulta **não muda**: o paciente recebe um pedido (`POST /api/consultas/{id}/solicitacoes`) e a alteração só acontece quando ele aceita (`POST /api/notificacoes/{id}/responder`), pela mesma operação atômica com `SELECT ... FOR UPDATE`. Se o paciente já confirmou pessoalmente ou por telefone, a equipe pode marcar "aplicar agora", e o paciente recebe um aviso.
- O paciente vê os pedidos no sino de notificações (com contador) e também no chat, onde responde com "sim" ou "não".
- Quando o paciente cancela pelo chat, o médico vinculado à consulta e as atendentes recebem um aviso; quando ele responde a um pedido, quem pediu também é avisado.
- `GET /api/notificacoes` lista as notificações pendentes do usuário logado.

## Instalação

```bash
python -m venv .venv
.venv\Scripts\activate
pip install -r app/backend/requirements.txt -r app/frontend/requirements.txt
```

## Configuração

Copie `app/backend/.env.example` para `app/backend/.env` e ajuste as variáveis (o arquivo é lido independentemente do diretório de execução).

O front-end lê as variáveis de ambiente a partir de `app/frontend/.env` (copie `app/frontend/.env.example` para esse caminho) ou do ambiente do sistema. Configure `DATABASE_URL`, `DJANGO_SECRET_KEY`, `DJANGO_DEBUG` e `DJANGO_ALLOWED_HOSTS`; `FASTAPI_BASE_URL` é opcional e usa `http://127.0.0.1:8000/api` por padrão.

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

Qualquer banco criado antes do vínculo entre a conta do médico e a ficha dele:

```sql
ALTER TABLE medicos ADD COLUMN usuario_id INTEGER REFERENCES usuarios(id);
CREATE UNIQUE INDEX IF NOT EXISTS uq_medicos_usuario_id ON medicos (usuario_id);
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

Usuários de demonstração (senha `senha123`): `gestor@clinica.com` (`gestor`), `recepcao@clinica.com` (atendente, `admin`), `joao.mendes@clinica.com` (`medico`), `lurdes@clinica.com` e `carlos@clinica.com` (`paciente`). Usuários de teste (senha `123456`): `paciente@teste.com`, `medico@teste.com` (Dr. Rafael Teixeira, Neurologia) e `atendente@teste.com`.

Depois do login, `/inicio/` leva cada perfil à sua área:

| Perfil | Área inicial | O que encontra |
|---|---|---|
| paciente | `/` (chat) | assistente e `/calendario/` com as próprias consultas |
| médico | `/medico/agenda/` | consultas do dia na própria agenda, além de tudo o que a atendente faz |
| atendente | `/gestao/` | painel com pacientes, cadastro de usuários, `/gestao/consultas/` (agendar, remarcar e cancelar) e `/gestao/horarios/` (liberar horários) |
| gestor | `/gestao/` | cadastro de médicos e atendentes |

Alterações e cancelamentos de consulta exigem marcar que o paciente confirmou.

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
