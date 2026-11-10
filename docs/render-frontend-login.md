# Frontend Django no Render: publicação e diagnóstico do login

## Escopo

Correções preparadas a partir de `8e3ed4a5d4a112ee7f846c5c9951fd16d7fab958`.
Não há alteração no FastAPI, modelos, migrações, contas ou dados existentes.
A conta administrativa continua sendo criada separadamente no backend; não executar seed de demonstração.

## Configuração

No serviço `assistente-frontend`:

- `DJANGO_DEBUG=false`.
- `DJANGO_ALLOWED_HOSTS=assistente-frontend.onrender.com` (sem protocolo).
- `DJANGO_CSRF_TRUSTED_ORIGINS=https://assistente-frontend.onrender.com`.
- `FASTAPI_BASE_URL=https://assistente-backend-7s5b.onrender.com/api`.
- `FASTAPI_TIMEOUT=30` (segundos; número entre zero, exclusivo, e 120).
- `DJANGO_SECRET_KEY`: segredo privado do Django.
- `DATABASE_URL`: conexão PostgreSQL/Neon do Django, sem publicá-la no Git.

`FASTAPI_BASE_URL` deve incluir `/api`, conforme o prefixo do backend deste projeto.
Valores de produção não podem apontar para localhost ou usar HTTP sem TLS.
O timeout não elimina o tempo de inicialização de serviços suspensos. Não há repetição automática de login nem de operações de cadastro.

O leitor de DATABASE_URL aceita postgres://, postgresql:// e postgresql+psycopg://.
Preserva os parâmetros de segurança suportados, incluindo sslmode e channel_binding.
Em produção, TLS é obrigatório. Não há fallback automático para SQLite.

## Render

Manter Root Directory `app/frontend`, Build Command `pip install -r requirements.txt && python manage.py collectstatic --noinput` e Start Command `python manage.py migrate --noinput && gunicorn setup.wsgi:application --bind 0.0.0.0:$PORT --workers 1 --timeout 120`.

Após revisar e integrar a correção à main, publicar o commit atualizado no frontend. Reiniciar uma versão antiga não atualiza o código.
As variáveis do painel continuam privadas; este patch não verifica nem modifica seus valores no Render.

Conferir o commit ativo em Events/Deploys e a tela /login/. Um HTTP 200 da página Django não comprova login na API.
O fluxo é navegador -> Django -> FastAPI -> PostgreSQL. A requisição Django/FastAPI não aparece como uma chamada separada no Network do navegador.

## Logs do login

O logger `assistant.login` informa apenas status HTTP e classe da causa. Não registra URL completa, e-mail, senha, token, corpo de resposta ou traceback.
Exemplos:

- `status=sem_resposta causa=ReadTimeout`: timeout aguardando a API.
- `status=sem_resposta causa=ConnectError`: falha de conexão.
- `status=404 causa=ApiIndisponivelError`: destino respondeu, mas a rota não existe.
- `status=503 causa=ApiIndisponivelError`: API indisponível.
- `status=200 causa=ValueError`: resposta recebida fora do contrato de login.

401/422 continuam sendo tratados como credenciais inválidas, sem criação de sessão.
Respostas 2xx com JSON ausente ou campos inválidos são tratadas como indisponibilidade, não como erro 500 da interface.

## Testes sem Neon e sem credenciais reais

Na pasta app/frontend:

```sh
python -m unittest discover -s tests -v
python manage.py test assistant --settings=setup.test_settings
```

A configuração setup.test_settings é EXCLUSIVA de testes e usa SQLite em memória. Não a configure como DJANGO_SETTINGS_MODULE no Render.
O teste local da configuração PostgreSQL não prova que o serviço publicado usa o mesmo banco.
A validação final de login com uma conta real precisa ser feita após a publicação, sem compartilhar senha ou token.

## Referências

- https://docs.djangoproject.com/en/6.0/howto/deployment/checklist/
- https://www.python-httpx.org/advanced/clients/
- https://render.com/docs/deploys
- https://neon.com/docs/connect/connect-securely
