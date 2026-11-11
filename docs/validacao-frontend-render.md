# Validação do frontend publicado no Render

## O que já está na main

O commit `ae4381aa8806cb0244f42079333c9c14297267f9`, aplicado pelo proprietário, já contém as correções de configuração Neon, validação de FASTAPI_BASE_URL, remoção das configurações duplicadas e diagnóstico seguro do login. Esta entrega não reaplica nem desfaz esse commit: acrescenta um diagnóstico executável e a validação automatizada que faltava.

Não há migração nova, criação de usuários ou alteração de preços, modelos, contas ou dados. Nenhum seed de demonstração é executado.

## Diagnóstico sem senha nem token

Na pasta `app/frontend`, com as variáveis do ambiente que deseja verificar:

```sh
python manage.py check_api
```

O comando faz no máximo duas requisições GET, sem repetição automática:

1. `/health` no host da API: exige HTTP 200 e JSON com `status: ok`.
2. `/api/auth/me`, sem credenciais: exige HTTP 401, conforme a proteção existente no FastAPI.

Não envia e-mail, senha, Authorization ou cookies. Cookies eventualmente devolvidos pelo health check são descartados. Não segue redirecionamentos e não imprime corpos de respostas, URLs com credenciais ou mensagens brutas de exceções.

Sucesso significa comunicação e respostas esperadas nessas rotas. Não prova a existência do gestor, validade da senha, disponibilidade do banco em todas as operações ou funcionamento da sessão autenticada. Uma resposta 401 sem credenciais é esperada nesse diagnóstico, mas não equivale a login bem-sucedido.

O diagnóstico usa a configuração do processo que o executou. Rodá-lo no computador local não comprova que o serviço do Render usa os mesmos valores. Ele não é executado durante o boot, build ou carregamento de páginas.

## Validação automatizada da PR

O workflow `Frontend Render validation` usa apenas credenciais fictícias e não recebe segredos do Neon/Render:

- Testes unitários de configuração, saída do login e transporte HTTP com MockTransport.
- Suíte Django com SQLite em memória, incluindo as regressões de login já aplicadas pelo proprietário.
- A mesma suíte Django em PostgreSQL 16 descartável do GitHub Actions; o Django cria e remove seu banco de teste.
- Verificação das dependências, system checks e coleta dos estáticos com a configuração de produção.

`setup.test_settings` e `setup.postgres_test_settings` são exclusivos de testes. Nunca configure esses módulos no Render. O segundo exige `TEST_POSTGRES_URL` para host local e banco `frontend_ci`, rejeitando destinos remotos, inclusive Neon. As senhas CI aparecem no workflow porque pertencem somente ao contêiner descartável.

Para executar os testes sem Neon:

```sh
python -m unittest discover -s tests -v
python manage.py test assistant --settings=setup.test_settings
```

## Publicação após revisão e merge

1. Confirmar no frontend `FASTAPI_BASE_URL=https://assistente-backend-7s5b.onrender.com/api`, `FASTAPI_TIMEOUT=30` e `DJANGO_DEBUG=false`.
2. Manter privados `DATABASE_URL` e `DJANGO_SECRET_KEY`. Usar o domínio real em DJANGO_ALLOWED_HOSTS e sua origem HTTPS em DJANGO_CSRF_TRUSTED_ORIGINS.
3. Integrar a PR apenas após revisar os testes. Publicar no frontend o commit novo, verificando o SHA em Events/Deploys. Reiniciar um deploy antigo não atualiza seu código.
4. Manter Root Directory `app/frontend`, Build Command `pip install -r requirements.txt && python manage.py collectstatic --noinput` e Start Command `python manage.py migrate --noinput && gunicorn setup.wsgi:application --bind 0.0.0.0:$PORT --workers 1 --timeout 120`.
5. Testar `/login/` com uma conta real previamente criada no FastAPI. Não usar o seed de demonstração para corrigir comunicação. Uma página Django HTTP 200 com mensagem de erro não é um login bem-sucedido.

Esta PR não modifica variáveis, reinicia serviços, faz deploy, integra a main ou acessa o Neon. Os ajustes do painel precisam ser conferidos no ambiente real; testes simulados ou banco descartável não validam credenciais de produção.

## Referências

- https://docs.djangoproject.com/en/dev/howto/custom-management-commands/
- https://docs.github.com/en/actions/tutorials/use-containerized-services/create-postgresql-service-containers
- https://render.com/docs/deploys
