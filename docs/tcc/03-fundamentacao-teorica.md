# 3. Fundamentação teórica

## 3.1 Sistemas de agendamento em ambientes clínicos

Sistemas de agendamento desempenham papel central na organização do fluxo de atendimento em clínicas e consultórios. Eles envolvem não apenas registros de consultas, mas também coordenação de agenda, disponibilidade e confirmação de horários. Quando bem implementados, esses sistemas ajudam a reduzir atrasos, evitar conflitos e melhorar a experiência do paciente.

## 3.2 Engenharia de software aplicada a sistemas de negócio

A construção de uma solução de agendamento pode ser organizada por meio de uma arquitetura em camadas, separando responsabilidades de persistência, regras de negócio, validação e interface de comunicação. Essa separação favorece manutenção, escalabilidade e testabilidade.

A arquitetura adotada neste projeto organiza o sistema em módulos específicos para banco de dados, modelos, repositórios, serviços, rotas e lógica de assistente virtual. Essa abordagem é alinhada aos princípios de modularização, coesão e baixo acoplamento.

## 3.3 Inteligência artificial e processamento de linguagem natural

Embora o protótipo atual utilize heurísticas e processamento estruturado de texto, ele já incorpora princípios fundamentais de IA aplicada ao processamento de linguagem natural. A partir de uma mensagem textual, o sistema identifica intenção, extrai dados relevantes e transforma esses dados em ações automatizadas.

Esse tipo de abordagem é uma base sólida para evoluções futuras com uso de modelos mais avançados, como redes de classificação para intenção, processamento com spaCy e modelos de recomendação baseados em dados históricos.

## 3.4 Validação e confiabilidade de software

A validação automatizada é essencial para um sistema que lida com entidades críticas como consultas médicas. Testes de API e integração permitem verificar que regras de negócio e fluxos principais continuam funcionando mesmo após mudanças no código.

No contexto do TCC, essa prática reforça a legitimidade técnica da solução, mostrando que o sistema não é apenas um protótipo visual, mas uma aplicação funcional, executável e testável.
