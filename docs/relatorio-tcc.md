# Documento de Apoio ao TCC

## 1. Título proposto

Desenvolvimento de um Assistente Virtual Inteligente para Agendamento e Gestão de Consultas Clínicas

## 2. Contexto e problema

A gestão de consultas clínicas envolve múltiplos desafios operacionais: organização de agenda, controle de disponibilidade, atendimento humano em momentos de alta demanda, confirmação de agendamentos e minimização de falhas de comunicação. Em ambientes de atenção primária e especializada, essas dificuldades geram atrasos, conflitos de agenda e perda de eficiência administrativa.

O sistema proposto visa reduzir esses problemas por meio de um assistente virtual capaz de interpretar mensagens em linguagem natural, identificar intenção de agendamento, recomendar horários disponíveis e apoiar a gestão de consultas em um ambiente de software estruturado.

## 3. Objetivo geral

Implementar um protótipo funcional de assistente virtual inteligente para agendamento e gestão de consultas médicas, com backend em Python, API REST com FastAPI, persistência relacional e regras de negócio alinhadas ao contexto clínico.

## 4. Objetivos específicos

- estruturar uma API robusta para gestão de pacientes, médicos, horários e consultas;
- implementar regras de negócio para confirmação, cancelamento e conflitos de agenda;
- disponibilizar um módulo de assistente que interprete mensagens em linguagem natural;
- permitir agendamento assistido via comando textual;
- sugerir a melhor opção de horário disponível por especialidade;
- validar o comportamento por testes automatizados.

## 5. Arquitetura do sistema

### 5.1 Arquitetura funcional

A solução foi organizada em camadas e módulos bem definidos:

- app/core: configuração, segurança e banco de dados;
- app/models: entidades do domínio;
- app/schemas: validação de entrada e saída;
- app/repositories: acesso à persistência;
- app/services: regras de negócio;
- app/routers: endpoints HTTP;
- app/assistant: lógica de interpretacão e recomendação;
- tests: validação automatizada.

### 5.2 Fluxo principal

1. o usuário registra ou autentica no sistema;
2. cria ou consulta médicos, pacientes e horários disponíveis;
3. envia uma mensagem em linguagem natural ao assistente;
4. a API identifica a intenção e extrai dados relevantes;
5. a aplicação valida disponibilidade e regras de negócio;
6. a consulta é criada ou a melhor sugestão é retornada ao usuário.

## 6. Modelo de domínio

Os principais elementos do domínio são:

- Usuario: responsável pela autenticação do sistema;
- Paciente: dados cadastrais do paciente;
- Medico: dados do profissional, CRM e especialidade;
- Horario: disponibilidade do médico em data e hora;
- Consulta: vínculo entre paciente, médico, horário e estado da consulta.

A modelagem foi concebida para preservar integridade referencial e evitar conflitos de agenda. O projeto também usa constraints de unicidade para impedir duplicidade de horários e reservas sobrepostos.

## 7. Regras de negócio implementadas

### 7.1 Agendamento

O agendamento exige:

- existência do paciente;
- existência do médico;
- existência do horário;
- disponibilidade real do slot;
- ausência de outra consulta ativa para o mesmo horário.

### 7.2 Confirmação

A alteração e o cancelamento de consulta exigem confirmação explícita do paciente, representada por campo booleano. Isso reduz ações acidentais e reforça segurança operacional.

### 7.3 Cancelamento

Quando uma consulta é cancelada:

- o status muda para "cancelada";
- o horário volta a ficar disponível;
- o sistema evita reuso indevido de slot já reservado por outra consulta ativa.

### 7.4 Assistente virtual

O assistente interpreta mensagens como:

- desejo de agendar consulta;
- dados de médico, data e hora;
- nome do paciente;
- especialidade de interesse.

O sistema também recomenda o melhor slot disponível para uma especialidade, priorizando a vaga mais rápida e próxima.

## 8. Aspectos de inteligência artificial e processamento de linguagem

Embora a implementação atual seja baseada em regras heurísticas e processamento estruturado de texto, a solução já atende ao princípio de um assistente virtual inteligente para uso em ambiente de clínica. O módulo de interpretação realiza:

- normalização textual;
- extração de dados semânticos;
- identificação de intenção;
- mapeamento de especialidade, data, hora e entidade clínica.

Essa base é adequada para evolução futura para modelos de NLP mais sofisticados, como processamento com spaCy, classificação de intenção, vetorização de mensagens e recomendação contextual.

## 9. Metodologia de desenvolvimento

A implementação foi conduzida em etapas incrementais, seguindo a lógica de validação contínua:

1. estrutura inicial do projeto;
2. modelagem de domínio e banco de dados;
3. APIs e autenticação;
4. regras de negócio e confirmação;
5. assistente virtual para agendamento;
6. recomendação de melhor vaga;
7. validação automatizada.

Essa abordagem favorece a rastreabilidade acadêmica e reduz riscos de falhas acumuladas em fases finais do desenvolvimento.

## 10. Validação e evidências

Os testes automatizados foram executados com pytest no ambiente do projeto. A execução final confirmou:

- 11 testes aprovados;
- 0 falhas;
- comando executado: python -m pytest -q no ambiente virtual do projeto.

A suíte cobre:

- autenticação;
- cadastro de pacientes e médicos;
- criação de horários;
- gestão de consultas;
- conflitos de agenda;
- confirmação e cancelamento;
- interpretação de mensagens do assistente;
- agendamento assistido;
- recomendação de melhor horário.

## 11. Justificativa acadêmica

A proposta é defensável como trabalho de TCC porque integra quatro pilares fundamentais:

- engenharia de software: organização em camadas, API REST, persistência e modularização;
- banco de dados: modelagem relacional, integridade e regras de negócio;
- inteligência artificial aplicada: interpretação de linguagem natural e recomendação de vagas;
- validação científica: testes automatizados e evidência de funcionamento.

Além disso, o projeto permite extensões acadêmicas relevantes, como:

- uso de NLP avançado;
- classificação de intenção com aprendizado de máquina;
- dashboard clínico para gestão de agenda;
- integração com lembretes e notificações.

## 12. Evolução prevista

Os próximos passos para fortalecer a proposta incluem:

- uso de spaCy para entendimentos mais robustos de linguagem natural;
- modelos de predição para disponibilidade e demanda;
- registro de histórico de interações do assistente;
- integração com notificações por e-mail e WhatsApp;
- autenticação mais granular por perfil de usuário;
- geração de relatórios administrativos e indicadores clínicos.

## 13. Conclusão

O protótipo desenvolvido atende ao objetivo de demonstrar um assistente virtual para agendamento e gestão de consultas clínicas com funcionalidade real, regras de negócio consistentes e validação automatizada. A estrutura atual é suficiente para sustentar a base do projeto de TCC, além de fornecer uma plataforma escalável para futuras melhorias acadêmicas e técnicas.
