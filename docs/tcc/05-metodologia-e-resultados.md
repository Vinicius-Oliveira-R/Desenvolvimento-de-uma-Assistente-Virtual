# 5. Metodologia e resultados

## 5.1 Metodologia

A metodologia deste trabalho seguiu uma abordagem incremental e orientada a validação. Em vez de construir uma solução apenas visualmente atraente, o projeto foi organizado em fases que incluíram modelagem do domínio, infraestrutura de banco de dados, autenticação, API, regras de negócio e lógica de assistente.

A cada etapa, foram realizados testes para confirmar que os comportamentos implementados estavam corretos. Essa estratégia foi importante para reduzir erros de integração e tornar o projeto mais sustentável.

## 5.2 Resultados obtidos

O sistema alcançou um conjunto de resultados relevantes:

- cadastro e autenticação de usuários;
- manutenção de pacientes e médicos;
- gestão de horários disponíveis;
- criação de consultas com validação de conflitos;
- confirmação e cancelamento com regras de negócio;
- interpretação de mensagens em linguagem natural;
- recomendação de horários compatíveis com a especialidade.

Esses resultados mostram que o protótipo atende ao objetivo principal do trabalho: oferecer um assistente virtual funcional para agendamento clínico.

## 5.3 Análise crítica

Apesar de funcional, o sistema ainda deve ser entendido como um protótipo. O assistente atual funciona com lógica heurística e interpreta mensagens por padrões. Para cenários mais complexos, a próxima evolução natural é a utilização de técnicas mais avançadas de NLP e ML, como classificadores de intenção, extração de entidades com spaCy e modelos de recomendação baseados em histórico de uso.

Mesmo assim, a solução é valida e defensável como projeto acadêmico porque demonstra implementação prática, engenharia de software aplicada e uso de critérios de qualidade relevantes para desenvolvimento de sistemas.
