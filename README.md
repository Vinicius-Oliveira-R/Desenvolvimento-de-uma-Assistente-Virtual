# Assistente Clínico

## Descrição

Protótipo de sistema para agendamento e gestão de consultas clínicas com assistente virtual em linguagem natural.

## Objetivo

Implementar uma API robusta em Python com FastAPI, banco relacional PostgreSQL e módulos de NLP/ML para apoiar o agendamento de consultas, gestão de disponibilidade e adaptação da comunicação.

## Tecnologias

- Python 3.11+
- FastAPI
- PostgreSQL
- SQLAlchemy
- Pydantic
- Alembic
- spaCy
- scikit-learn
- pytest

## Arquitetura

- app/core: configuração, segurança e banco
- app/models: entidades do domínio
- app/schemas: validação de entrada e saída
- app/repositories: persistência
- app/services: regras de negócio
- app/routers: endpoints da API
- app/assistant: processamento de intenção e diálogo
- app/ml: preparação e classificação de dados

## Instalação

```bash
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
```

## Configuração do banco

Copie o arquivo `.env.example` para `.env` e ajuste as variáveis.

## Execução

```bash
uvicorn app.main:app --reload
```

## Testes

```bash
pytest
```

## Estrutura do projeto

```text
assistente-clinico/
├── app/
│   ├── core/
│   ├── models/
│   ├── schemas/
│   ├── repositories/
│   ├── services/
│   ├── routers/
│   ├── assistant/
│   └── ml/
├── tests/
├── alembic/
├── .env.example
├── .gitignore
├── README.md
├── requirements.txt
└── app/main.py
```
