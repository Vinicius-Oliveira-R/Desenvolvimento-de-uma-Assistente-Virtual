# 4. Arquitetura e desenvolvimento

## 4.1 Visão geral da solução

A solução foi implementada em Python usando FastAPI como framework principal. O sistema conta com API REST, persistência em banco de dados relacional, modelos de domínio para pacientes, médicos, horários e consultas, além de uma camada de assistente virtual para interpretação de texto.

## 4.2 Estrutura do projeto

A organização do projeto foi pensada para separar as responsabilidades de cada componente. As principais partes incluem:

- modelos: entidades do domínio;
- serviços: regras de negócio;
- routers: endpoints HTTP;
- core: configurações e infraestrutura;
- assistant: lógica de interpretação e recomendação;
- tests: validação das funcionalidades.

## 4.3 Banco de dados e regras de negócio

O banco de dados armazena pacientes, médicos, horários, usuários e consultas. As regras de negócio foram implementadas no serviço de consultas e refletem necessidades reais do ambiente clínico:

- não é permitido agendar consulta em horário indisponível;
- não pode haver sobreposição de consultas para o mesmo médico;
- o paciente e o médico devem existir antes do agendamento;
- consultas só podem ser alteradas ou canceladas após confirmação;
- a cancelamento reabre o horário correspondente.

Essas regras tornam o sistema mais confiável e alinhado com o objetivo de apoio à gestão clínica.

## 4.4 Assistente virtual

A lógica do assistente interpreta mensagens do tipo:

- agendar consulta com o cardiologista amanhã às 14h;
- marcar uma consulta para Maria com endocrinologia no dia 15/12;
- qual é o melhor horário para dermatologia?

A partir dessas mensagens, o sistema extrai entidades, identifica a intenção do usuário e executa a ação correspondente. Em casos de recomendação, o sistema compara horários disponíveis e escolhe a melhor alternativa.

## 4.5 Validação técnica

O sistema foi validado por testes automatizados, com foco em cenários reais de uso. Isso inclui registros de usuários, criação de médicos e pacientes, agendamento, conflito de horários, cancelamento, confirmação e funcionamento do assistente.

Esse conjunto de verificações mostra que a implementação não ficou restrita a um código estático, mas oferece comportamento verificável e repetível.
