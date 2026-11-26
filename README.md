# Assistente Clínico

Protótipo de agendamento administrativo com FastAPI, SQLAlchemy/PostgreSQL,
Django SSR, HTTPX, HTMX, Alpine.js e Bootstrap. O PLN de intenção utiliza
spaCy (Matcher/EntityRuler). A idade do cadastro define o estilo inicial da conversa e o
Random Forest é apenas um sinal adicional de estilo: não diagnostica doenças nem comprova
idade do paciente.

## Revisão da auditoria

As correções e sua rastreabilidade estão em
[docs/auditoria-codigo-20261113.md](docs/auditoria-codigo-20261113.md). A revisão da conversa
do paciente (confirmações, estilo, escolhas, retomada e login com 429) está em
[docs/revisao-conversa-20261126.md](docs/revisao-conversa-20261126.md).
Este é um protótipo: testes não certificam segurança, adequação clínica,
acessibilidade, conformidade jurídica ou disponibilidade de produção.

**Esta revisão altera o schema. Não publicar sobre banco antigo sem migração.**
Não executar testes ou seed demonstrativo no Neon de produção. A retirada de
credenciais padrão do código não redefine contas que já utilizaram esses valores.

## Instalação e configuração

Use Python 3.12, conforme a integração contínua, e um ambiente virtual:

```bash
python -m venv .venv
# Windows: .venv\Scripts\activate
# Linux/macOS: source .venv/bin/activate
python -m pip install -r app/backend/requirements.txt -r app/frontend/requirements.txt
```

Copie os arquivos `.env.example` para `.env` nas pastas correspondentes.
O backend requer `DATABASE_URL` e `SECRET_KEY` aleatória exclusiva (>=32 caracteres).
Não use os segredos dos testes. O exemplo não contém uma chave de produção.
A validade JWT padrão é 60 minutos, limitada por configuração a 480 minutos.

O frontend utiliza `DATABASE_URL`, `DJANGO_SECRET_KEY`, `DJANGO_DEBUG`,
`DJANGO_ALLOWED_HOSTS`, `DJANGO_CSRF_TRUSTED_ORIGINS`, `FASTAPI_BASE_URL`
e `FASTAPI_TIMEOUT`. Em produção a URL da API deve ser HTTPS e terminar em `/api`.
Consulte também [docs/render-frontend-login.md](docs/render-frontend-login.md).

## Banco existente e publicação

1. Fazer backup e ensaiar em uma cópia de homologação.
2. Na raiz, executar `python -m app.backend.migrate --check` (somente leitura).
3. Resolver conflitos de dados existentes de forma administrativa, sem apagar o histórico.
4. Executar `python -m app.backend.migrate --apply` com a role proprietária do schema.
5. Publicar backend e frontend da mesma revisão validada; fazer novo login.

A migração é aditiva/idempotente e transacional no PostgreSQL: adiciona estado
ativo, versão do token, contadores de login e proteção de intervalos com `btree_gist`.
Recusa sobreposições, datas inválidas e e-mails duplicados por caixa; não corrige
esses dados automaticamente. `create_all` sozinho não atualiza tabelas antigas.
Tokens anteriores sem versão são rejeitados após esta atualização.

## Primeiro gestor e recuperação

```bash
python -m app.backend.create_gestor
python -m app.backend.create_gestor --redefinir
```

O primeiro comando cria somente o gestor inicial; o segundo redefine a senha de
um gestor ativo existente e revoga seus tokens. Exigem entrada oculta e confirmação
do destino; não promovem contas comuns nem criam dados de demonstração.
O `seed.py` contém exemplos de desenvolvimento: nunca executá-lo em produção.

## Execução local

```bash
python -m uvicorn app.backend.main:app --reload
# Em outro terminal:
cd app/frontend
python manage.py migrate
python manage.py runserver 8001
```

O servidor da API usa `/api` e a documentação fica em `/docs`; saúde em `/health`.
A interface Django envia operações autenticadas ao backend. Não confundir a senha
do usuário com o segredo JWT ou a conexão PostgreSQL.

## Perfis e interfaces

`admin` é o código do atendente; `gestor` é um papel separado, não um superusuário
com acesso automático a todas as operações clínicas. Os papéis são lidos no banco
a cada requisição; contas inativas ou tokens revogados são recusados.

| Papel | Cadastro de usuários | Agenda clínica | Área inicial |
|---|---|---|---|
| gestor | médicos e atendentes | não administra consultas pela política atual | `/gestao/` |
| admin (atendente) | pacientes e atendentes | disponibiliza, agenda, remarca e cancela | `/gestao/` |
| medico | pacientes, atendentes e médicos | agenda diária e operações da equipe | `/medico/agenda/` |
| paciente | não | próprias consultas pelo chat e listagem | `/` |

Ninguém cadastra gestor pela API. A matriz está em `models/usuario.py` e deve ser
revista pela instituição antes do uso real. Não existe validação automática do CRM
junto ao conselho profissional.

O paciente pode editar e-mail/telefone em `/meus-dados/`; a equipe tem o atalho
Editar contato na listagem. O gestor administra ativação de profissionais em
`/gestao/profissionais/`. Desativar um profissional impede novas vagas/reservas,
mas não apaga consultas existentes nem cancela compromissos silenciosamente.

## Fluxo conversacional

Pedidos genéricos buscam Clínica Geral explicitamente (se a clínica não tiver clínico
geral, o assistente pergunta a especialidade). Uma especialidade ou médico já escolhido
é preservado. As opções vêm de horários futuros e disponíveis no banco; listar não
reserva. O paciente escolhe e confirma antes da gravação.

**Confirmações.** Só alteram a agenda as perguntas de confirmação (marcar, trocar,
desmarcar e responder a pedido da clínica), e só com a frase inteira de concordância
("sim", "pode marcar", "confirmo") ou com o botão que nomeia a ação: *Confirmar horário*,
*Confirmar troca*, *Desmarcar consulta* e *Manter minha consulta*. Perguntas e dúvidas
("pode repetir?", "quero entender", "como assim?", "já está marcado?", "não sei")
reapresentam a etapa sem mudar nada. Cada pergunta recebe uma proposta nova; um botão
de uma pergunta anterior é recusado. Antes de gravar, paciente, consulta e vaga são
conferidos de novo; um clique duplo informa a reserva já registrada em vez de criar outra.

**Escolhas.** Valem toque, número, número por extenso, ordinal e referência a um horário
exibido ("2", "dois", "opção dois", "a segunda", "o das duas da tarde"). "Segunda" com uma
opção 2 na tela gera uma pergunta curta (opção ou segunda-feira); dois horários iguais são
distinguidos por data ou médico; uma opção inexistente é explicada com as opções reais.

**Estilo.** A idade em anos completos é calculada no backend a partir do cadastro e só
define a apresentação inicial: a partir de `ASSISTENTE_IDADE_PASSO_A_PASSO` (60) ou com
data ausente/inválida, uma pergunta por vez e até duas opções; abaixo disso, o estilo
direto (até seis). Pedidos explícitos têm prioridade — os comandos `modo simples`,
`modo padrão` e `modo automático` continuam válidos, além de "explique melhor", "vá por
partes", "seja mais direto" e "mostre mais horários". Um pedido de ajuda ("não entendi")
passa ao passo a passo. O classificador Random Forest permanece como último sinal: só
mensagens com quatro ou mais palavras contam e a troca exige evidência continuada
(histerese), para o estilo não alternar a cada resposta curta. O paciente não escolhe
nem vê rótulos etários, probabilidades ou o diagnóstico do classificador; a resposta da
API informa apenas o estilo neutro (`passo_a_passo` ou `direto`) e guarda a evidência do
classificador cifrada no contexto. Detalhes e limitações
estão em `app/backend/assistant/communication_style.py`.

**Retomada.** `/api/assistant/retomar` reapresenta a etapa pendente (revalidando a vaga)
ao atualizar ou voltar ao chat; sem etapa, mostra *Marcar consulta*, *Minhas consultas*
e *Mudar ou cancelar*. *Novo agendamento* encerra a proposta anterior e inicia outra
busca, sem tocar nas consultas registradas. Se a conexão cair depois de uma confirmação,
o chat orienta a conferir *Minhas consultas* antes de repetir.

A remarcação pelo chat mostra o horário atual e o proposto e aproveita pedidos completos
("mudar minha consulta de sexta para segunda à tarde"). A transferência é atômica: se o
destino ficar ocupado, a consulta original é preservada. Pedidos de alteração enviados
pela equipe e notificações continuam disponíveis, respeitando a confirmação do paciente.

Rotas legadas de leitura exigem autenticação; `/api/assistant/agendar` foi retirada
do fluxo de escrita e retorna 410 para usuário autenticado. Use `/api/assistant/chat`.

Falhas de treino/predição do classificador não mudam o estilo definido pela idade ou
pelo paciente e não bloqueiam a agenda determinística. A espera é limitada e não são
criadas threads sem limite.

## Testes e evidências

```bash
python -m pytest app/backend/tests -q
python -m app.backend.ml.train --output evidence/classifier.json
cd app/frontend
python manage.py test assistant --settings=setup.test_settings
python -m unittest discover -s tests -v
```

`assistant.test_fluxo_integrado` percorre o chat real (sessão, formulários e templates do
Django) chamando a API FastAPI no mesmo processo, num SQLite temporário, e confere a tela e
o banco. Ele é ignorado quando as dependências do backend não estão instaladas; o workflow
`fluxo-paciente.yml` instala as duas e o executa.

Os testes PostgreSQL somente rodam quando `TEST_POSTGRES_URL` aponta para banco
**descartável**, pois recriam tabelas. Nunca usar a URL Neon real. O CI utiliza
PostgreSQL 16 temporário e registra JUnit, commit, versões e métricas do modelo.
O frontend também é testado em SQLite temporário e PostgreSQL descartável.

O critério do modelo é média de F1 macro >=0,80 em cinco folds estratificados com
semente 42. O relatório JSON contém distribuição/hash do corpus, parâmetros,
predições por linha e matriz de confusão. Não representa validação externa ou
experimento de usabilidade. Não há comprovação de p95 sem ensaio de carga dedicado.

A documentação anterior de concepção permanece em
[docs/historico/relatorio-tcc-inicial.md](docs/historico/relatorio-tcc-inicial.md),
identificada como histórica; suas contagens de testes não descrevem esta revisão.
